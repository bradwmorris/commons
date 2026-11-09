from pathlib import Path
from html import escape
import xml.etree.ElementTree as ET
P=Path(__file__).resolve().parent
BG='#101212';WHITE='#E9EEEA';MUTED='#A4AEA8';EDGE='#43524A';GREEN='#68DF99';BLUE='#8AC5DF'
s=[]
def brand(name,x,y,size=76):
 node=ET.parse(P/'brand-icons'/name).getroot()
 allowed={'svg','g','title','path','defs','linearGradient','radialGradient','stop','rect','circle','ellipse','polygon','polyline','line','style'}
 for e in node.iter():
  assert e.tag.split('}')[-1] in allowed,e.tag
  assert not any(k.lower().startswith('on') or k.endswith('href') for k in e.attrib)
 ET.register_namespace('', 'http://www.w3.org/2000/svg')
 node.set('x',str(x-size/2));node.set('y',str(y-size/2));node.set('width',str(size));node.set('height',str(size))
 node.set('style','color:#E9EEEA');node.set('fill',node.get('fill','none').replace('currentColor','#E9EEEA'))
 for e in node.iter():
  for k,v in list(e.attrib.items()):
   if v=='currentColor':e.set(k,'#E9EEEA')
 add(ET.tostring(node,encoding='unicode'))
def add(x):s.append(x)
def label(x,y,t,size=24,c=WHITE,weight=500,anchor='middle',spacing=None):
 add(f'<text x="{x}" y="{y}" font-family="Arial, Helvetica, sans-serif" font-size="{size}" font-weight="{weight}" fill="{c}" text-anchor="{anchor}"'+(f' letter-spacing="{spacing}"' if spacing else '')+f'>{escape(t)}</text>')
def line(d,c=EDGE,w=2.5):add(f'<path d="{d}" fill="none" stroke="{c}" stroke-width="{w}" stroke-linecap="round" stroke-linejoin="round"/>')
def rect(x,y,w,h,stroke=EDGE,fill='#171D19',r=20):add(f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="{r}" fill="{fill}" stroke="{stroke}" stroke-width="2"/>')
def head(x,y,dx,dy,c=GREEN):
 # Arrowhead tip and unit travel direction.
 add(f'<path d="M {x} {y} L {x-dx*12-dy*5} {y-dy*12+dx*5} L {x-dx*12+dy*5} {y-dy*12-dx*5} Z" fill="{c}"/>')
def person(x,y):
 add(f'<circle cx="{x}" cy="{y}" r="13" fill="none" stroke="{MUTED}" stroke-width="3"/>')
 line(f'M {x-27} {y+48} C {x-27} {y+17}, {x+27} {y+17}, {x+27} {y+48}',MUTED,3)
def terminal(x,y):
 rect(x-39,y-26,78,56,GREEN,'none',9)
 line(f'M {x-23} {y-10} L {x-10} {y} L {x-23} {y+10} M {x+1} {y+12} H {x+21}',GREEN,3)
def model(x,y):
 line(f'M {x} {y-16} Q {x+4} {y-4} {x+16} {y} Q {x+4} {y+4} {x} {y+16} Q {x-4} {y+4} {x-16} {y} Q {x-4} {y-4} {x} {y-16} Z',MUTED,2)
def loop(x,y):
 line(f'M {x+13} {y-4} A 14 14 0 1 0 {x+8} {y+12} M {x+13} {y-14} V {y-3} H {x+2}',MUTED,2)
def tools(x,y):
 line(f'M {x-12} {y+12} L {x+2} {y-2} M {x+2} {y-2} C {x-3} {y-12}, {x+8} {y-19}, {x+14} {y-12} L {x+6} {y-6} L {x+12} {y} C {x+7} {y+7}, {x+1} {y+4}, {x+2} {y-2}',MUTED,2)
add('<svg xmlns="http://www.w3.org/2000/svg" width="1600" height="1000" viewBox="0 0 1600 1000" role="img" aria-labelledby="title desc">')
add('<title id="title">Your agents connect to the shared system you own</title>')
add('<desc id="desc">Four people use Claude Code, Codex, Hermes and Pi, each with its own model, harness and tools. Separate MCP connectors expose Search, Read and Write. The agents connect to Commons, which keeps its API and shared PostgreSQL knowledge outside the agents. Arrows show two-way access.</desc>')
add(f'<rect width="1600" height="1000" fill="{BG}"/>')
label(800,63,'YOUR AGENTS',21,MUTED,700,spacing=3)
for x,name,icon in [(260,'Claude Code','claudecode-color.svg'),(620,'Codex','codex-color.svg'),(980,'Hermes','hermesagent.svg'),(1340,'Pi','pi-coding-agent.svg')]:
 person(x,109)
 line(f'M {x} 169 V 190',EDGE,2)
 rect(x-145,200,290,181)
 brand(icon,x,245,84 if name=='Pi' else 76)
 label(x,311,name,28,WHITE,700)
 model(x-61,350);loop(x,350);tools(x+61,350)
 # Each client has its own connector; these are not a central hosted MCP runtime.
 rect(x-48,399,96,43,EDGE,BG,10)
 line(f'M {x} 381 V 399',EDGE,2)
 label(x,428,'MCP',19,MUTED,700,spacing=1.5)
 line(f'M {x-8} 450 V 505',GREEN,2.5);head(x-8,450,0,-1)
 line(f'M {x+8} 450 V 505',GREEN,2.5);head(x+8,505,0,1)
# A shared line represents the protocol route, not an extra service.
line('M 252 505 H 1348',GREEN,2.5)
label(800,553,'SEARCH  ·  READ  ·  WRITE',20,GREEN,700,spacing=2)
# Single owned-system boundary.
rect(150,610,1300,315,GREEN,'#122019',24)
label(204,662,'COMMONS',25,GREEN,700,'start',3)
label(204,697,'Your shared system',22,MUTED,400,'start')
line('M 792 570 V 673',GREEN,2.5);head(792,570,0,-1)
line('M 808 570 V 673',GREEN,2.5);head(808,673,0,1)
# API icon / central access gate.
rect(682,673,236,116,EDGE,'#101713',16)
line('M 738 704 L 727 716 L 738 728 M 862 704 L 873 716 L 862 728',GREEN,3)
label(800,751,'API',27,WHITE,700)
line('M 792 789 V 815',GREEN,2.5);head(792,789,0,-1)
line('M 808 789 V 815',GREEN,2.5);head(808,815,0,1)
# PostgreSQL as database, without falsely inventing a vendor logo.
add(f'<path d="M 731 836 V 875 C 731 897 869 897 869 875 V 836" fill="#182C34" stroke="{BLUE}" stroke-width="3"/>')
add(f'<ellipse cx="800" cy="836" rx="69" ry="18" fill="#243F4C" stroke="{BLUE}" stroke-width="3"/>')
label(982,845,'Shared knowledge',25,WHITE,700,'start')
label(982,879,'PostgreSQL',19,MUTED,400,'start')
# Tiny conceptual legend for the agent internals, stated once rather than three times.
label(800,969,'Agent = model + harness + tools',19,MUTED,400)
add('</svg>')
(P/'commons-components-v3.svg').write_text('\n'.join(s)+'\n')
print(P/'commons-components-v3.svg')
