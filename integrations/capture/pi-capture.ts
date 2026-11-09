/** Live turn capture; config path explicitly opts in. Never reads session history. */
import { randomUUID } from 'node:crypto';
import { spawn } from 'node:child_process';
import { Type } from 'typebox';
import type { ExtensionAPI } from '@earendil-works/pi-coding-agent';
export default function(pi: ExtensionAPI) {
  const config = process.env.COMMONS_PI_CAPTURE_CONFIG;
  const bridge = process.env.COMMONS_PI_CAPTURE_BRIDGE;
  let turn: any = null;
  let position = Date.now() * 1000;
  const now = () => new Date().toISOString();
  const model = (m:any) => m ? {provider:m.provider ?? null,id:m.id ?? m.model ?? null} : {provider:null,id:null};
  pi.on('model_select',async event=>{
    if(turn) { const observed={...model(event.model),at:now()};turn.models.push(observed);turn.events.push({event:'model_select',...observed}); }
  });
  const text = (m:any) => typeof m.content === 'string' ? m.content :
    (m.content || []).filter((b:any)=>b.type==='text').map((b:any)=>b.text).join('\n');
  pi.on('input', async (event,ctx) => {
    // Overlapping input is excluded rather than attributed to the wrong human turn.
    if (turn) { turn.domain='mixed'; turn.overlap=true; return; }
    turn={session:ctx.sessionManager.getSessionId(),turn:randomUUID(),domain:'unclassified',
      started_at:now(),position,items:[{kind:'message',role:'human',body:event.text,at:now()}],events:[],models:[{...model(ctx.model),at:now()}]};
  });
  pi.on('before_agent_start', async event => ({systemPrompt:event.systemPrompt+
    '\nBefore substantive work, call commons_capture_route with business only for wholly business work; personal/mixed otherwise. Unclassified turns are excluded. Do not capture hidden reasoning.'}));
  pi.registerTool({name:'commons_capture_route',label:'Route Commons capture',
    description:'Classify this human turn using existing business/personal instructions before substantive work. Personal, mixed and unclassified turns are excluded in full.',
    parameters:Type.Object({domain:Type.Union([Type.Literal('business'),Type.Literal('personal'),Type.Literal('mixed')])}),
    async execute(_id,args) {
      if(!turn) throw new Error('No live human turn');
      if(turn.overlap) throw new Error('Overlapping input excluded');
      if(turn.domain!=='unclassified' && turn.domain!==args.domain) {turn.domain='mixed';throw new Error('Conflicting routing excluded');}
      turn.domain=args.domain;
      return {content:[{type:'text',text:JSON.stringify({domain:turn.domain,enabled:!!config})}],details:{}};
    }});
  pi.on('message_end',async event=>{
    if(!turn || event.message.role!=='assistant') return;
    const body=text(event.message);if(body) turn.items.push({kind:'message',role:'agent',body,at:now(),model:{provider:event.message.provider ?? null,id:event.message.model ?? null}});
  });
  pi.on('tool_execution_start',async event=>{
    if(!turn) return;
    turn.items.push({kind:'tool_call',role:'agent',body:JSON.stringify(event.args),at:now(),tool_name:event.toolName,tool_call_id:event.toolCallId});
    turn.events.push({event:'tool_start',at:now(),name:event.toolName,id:event.toolCallId});
  });
  pi.on('tool_execution_end',async event=>{
    if(!turn) return;
    turn.items.push({kind:'tool_result',role:'tool',body:JSON.stringify(event.result),at:now(),tool_name:event.toolName,tool_call_id:event.toolCallId});
    turn.events.push({event:'tool_end',at:now(),name:event.toolName,id:event.toolCallId,error:event.isError,duration_ms:event.durationMs});
  });
  pi.on('agent_settled',async (_event,ctx)=>{
    const done=turn;turn=null;if(!done) return;position+=done.items.length+1;
    if(done.domain!=='business' || !config || !bridge) return;
    done.completed_at=now();done.events.push({event:'agent_settled',at:done.completed_at});
    try {
      await new Promise<void>((resolve,reject)=>{
        const child=spawn(process.env.COMMONS_PI_PYTHON || 'python3',[bridge,'--config',config],{stdio:['pipe','pipe','pipe']});
        child.stdout.resume();child.stderr.resume();
        const timeout=setTimeout(()=>child.kill('SIGTERM'),45000);
        child.on('error',error=>{clearTimeout(timeout);reject(error);});
        child.on('close',code=>{clearTimeout(timeout);code===0?resolve():reject(new Error('Capture delivery failed; inspect private outbox'));});
        child.stdin.end(JSON.stringify(done));
      });
    } catch {ctx.ui.notify('Commons capture delivery failed; inspect private outbox.','error');}
  });
}
