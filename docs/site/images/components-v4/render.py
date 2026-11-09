from pathlib import Path
from html import escape
import xml.etree.ElementTree as ET
P=Path(__file__).resolve().parent
ICONS=P.parent/'components-v3/brand-icons'
BG='#101212';WHITE='#E9EEEA';MUTED='#A4AEA8';EDGE='#43524A';GREEN='#68DF99';BLUE='#8AC5DF';AMBER='#DDBA7B'
s=[]
def add(t):s.append(t)
def text(x,y,t,size=24,c=WHITE,weight=500,anchor='middle',spacing=None):
 add(f'<text x="{x}" y="{y}" font-family="Arial, Helvetica, sans-serif" font-size="{size}" font-weight="{weight}" fill="{c}" text-anchor="{anchor}"'+(f' letter-spacing="{spacing}"' if spacing else '')+f'>{escape(t)}</text>')
def path(d,c=EDGE,w=2.5,dash=False):
 add(f'<path d="{d}" fill="none" stroke="{c}" stroke-width="{w}" stroke-linecap="round" stroke-linejoin="round"'+(' stroke-dasharray="8 8"' if dash else '')+'/>')
def box(x,y,w,h,stroke=EDGE,fill='#171D19',r=20,dash=False):
 add(f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="{r}" fill="{fill}" stroke="{stroke}" stroke-width="2"'+(' stroke-dasharray="8 8"' if dash else '')+'/>')
def tip(x,y,dx,dy,c=GREEN):
 add(f'<path d="M {x} {y} L {x-dx*12-dy*5} {y-dy*12+dx*5} L {x-dx*12+dy*5} {y-dy*12-dx*5} Z" fill="{c}"/>')
def person(x,y):
 add(f'<circle cx="{x}" cy="{y}" r="12" fill="none" stroke="{MUTED}" stroke-width="3"/>')
 path(f'M {x-25} {y+45} C {x-25} {y+17}, {x+25} {y+17}, {x+25} {y+45}',MUTED,3)
def brand(name,x,y,size=72):
 root=ET.parse(ICONS/name).getroot();ET.register_namespace('','http://www.w3.org/2000/svg')
 root.set('x',str(x-size/2));root.set('y',str(y-size/2));root.set('width',str(size));root.set('height',str(size));root.set('style','color:'+WHITE)
 for e in root.iter():
  for k,v in list(e.attrib.items()):
   if v=='currentColor':e.set(k,WHITE)
 add(ET.tostring(root,encoding='unicode'))
def skill(x,y):
 path(f'M {x-17} {y-22} H {x+6} L {x+17} {y-11} V {y+22} H {x-17} Z M {x+6} {y-22} V {y-11} H {x+17} M {x-8} {y+1} H {x+8} M {x-8} {y+11} H {x+8}',AMBER,3)
def tool(x,y):
 path(f'M {x-18} {y+18} L {x+1} {y-1} M {x+1} {y-1} C {x-6} {y-14}, {x+10} {y-25}, {x+20} {y-15} L {x+8} {y-7} L {x+16} {y+2} C {x+9} {y+12}, {x-1} {y+7}, {x+1} {y-1}',AMBER,3)
def flow(x,y):
 for xx,yy in [(x,y-14),(x-19,y+17),(x+19,y+17)]:box(xx-7,yy-7,14,14,AMBER,'#1F1C16',3)
 path(f'M {x} {y-7} V {y+1} H {x-19} V {y+10} M {x} {y+1} H {x+19} V {y+10}',AMBER,2.5)
add('<svg xmlns="http://www.w3.org/2000/svg" width="1800" height="1250" viewBox="0 0 1800 1250" role="img" aria-labelledby="title desc">')
add('<title id="title">Shared and accumulating context and capabilities</title>')
add('<desc id="desc">People bring Claude Code, Codex, Hermes and Pi. Their three database tools connect through MCP to a Rust API and shared PostgreSQL context. Green arrows write findings back; blue arrows read and reuse context across agents. A separate amber overlay holds organisation-specific skills, tools and workflows, with its own use and improvement loop to the agents. The context service and overlay form a system outside the agents.</desc>')
add(f'<rect width="1800" height="1250" fill="{BG}"/>')
text(860,58,'YOUR AGENTS',23,MUTED,700,spacing=3)
# Group boundary makes the overlay attach to all agents, not just the nearest product.
box(100,176,1520,221,EDGE,'none',24)
for x,name,icon in [(260,'Claude Code','claudecode-color.svg'),(650,'Codex','codex-color.svg'),(1040,'Hermes','hermesagent.svg'),(1430,'Pi','pi-coding-agent.svg')]:
 person(x,100);path(f'M {x} 153 V 200',EDGE,2)
 box(x-142,200,284,172)
 brand(icon,x,245,84 if name=='Pi' else 72)
 text(x,321,name,29,WHITE,700)
 text(x,350,'Model · harness · tools',17,MUTED)
 path(f'M {x} 372 V 421',EDGE,2)
 box(x-48,421,96,49,EDGE,BG,10);text(x,453,'MCP',20,MUTED,700,spacing=1)
# One lane for writes, one for reads. A small gap marks line crossings, not junctions.
for a,b in [(272,628),(648,1018),(1038,1408),(1428,1442)]:
 if b>a:path(f'M {a} 520 H {b}',GREEN,3)
for x in [260,650,1040,1430]:
 path(f'M {x+12} 470 V 520',GREEN,3);tip(x+12,511,0,1,GREEN)
 path(f'M {x-12} 560 V 470',BLUE,3);tip(x-12,470,0,-1,BLUE)
# Fill the write-lane crossings with bridge arcs above the read branch.
for x in [638,1028,1418]:path(f'M {x-10} 520 Q {x} 504 {x+10} 520',GREEN,3)
path('M 248 560 H 1418',BLUE,3)
# Labels make the accumulated, cross-agent reuse loop explicit.
text(350,614,'WRITE BACK',22,GREEN,700,spacing=2)
text(1280,614,'READ & REUSE',22,BLUE,700,spacing=2)
text(1080,665,'SEARCH · READ · WRITE',20,MUTED,600,spacing=1.5)
# System boundary and two explicitly distinct owners within it.
box(100,710,1520,450,EDGE,'#111914',24)
text(140,755,'SHARED AND ACCUMULATING',25,WHITE,700,'start',1)
text(140,792,'CONTEXT AND CAPABILITIES',25,WHITE,700,'start',1)
box(140,830,860,280,GREEN,'#122019',18)
text(176,873,'CONTEXT',23,GREEN,700,'start',2)
text(176,906,'Base repo',20,MUTED,400,'start')
box(600,850,280,80,EDGE,'#101713',14);text(740,900,'Rust API',29,WHITE,700)
# Every context read/write goes through the Rust API.
path('M 772 520 V 850',GREEN,3);tip(772,850,0,1,GREEN)
path('M 748 850 V 560',BLUE,3);tip(748,560,0,-1,BLUE)
path('M 772 930 V 982',GREEN,3);tip(772,982,0,1,GREEN)
path('M 748 982 V 930',BLUE,3);tip(748,930,0,-1,BLUE)
add(f'<path d="M 684 1001 V 1052 C 684 1076 816 1076 816 1052 V 1001" fill="#182C34" stroke="{BLUE}" stroke-width="3"/>')
add(f'<ellipse cx="750" cy="1001" rx="66" ry="19" fill="#243F4C" stroke="{BLUE}" stroke-width="3"/>')
text(470,1021,'PostgreSQL',27,WHITE,700)
text(470,1056,'Accumulating context',19,MUTED)
box(1060,830,520,280,AMBER,'#1F1C16',18,True)
text(1094,875,'CAPABILITIES',23,WHITE,700,'start',2)
text(1546,875,'OVERLAY',18,AMBER,700,'end',2)
for y,title,fn in [(939,'Skills',skill),(1002,'Tools',tool),(1065,'Workflows',flow)]:
 fn(1130,y);text(1190,y+9,title,27,WHITE,600,'start')
# Capabilities are attached independently; they do not travel through the database API.
path('M 1580 957 H 1690 V 277 H 1620',AMBER,2.6,True);tip(1620,277,-1,0,AMBER)
path('M 1620 331 H 1732 V 1020 H 1580',AMBER,2.6,True);tip(1580,1020,-1,0,AMBER)
add(f'<text transform="translate(1675 652) rotate(-90)" font-family="Arial, Helvetica, sans-serif" font-size="20" font-weight="600" fill="{AMBER}" text-anchor="middle">Use capabilities</text>')
add(f'<text transform="translate(1768 652) rotate(90)" font-family="Arial, Helvetica, sans-serif" font-size="20" font-weight="600" fill="{AMBER}" text-anchor="middle">Improve capabilities</text>')
text(860,1211,'One agent’s findings become another agent’s starting point.',24,MUTED)
add('</svg>')
(P/'shared-context-capabilities-v4.svg').write_text('\n'.join(s)+'\n')
(P/'brief.txt').write_text('''Draft v4, for review only. Do not publish until reviewed.
Required title: Shared and accumulating context and capabilities. No Commons label.
Four external agents with existing inspected brand artwork. People above each.
Base repo context lane: three tools via MCP -> Rust API -> PostgreSQL. Green writes, blue reads and reuse. All context access crosses the API. Cross-agent accumulation is represented by the shared write/read lanes and the final caption.
Separate organisation-specific capabilities overlay: Skills, Tools, Workflows. Amber dashed use/improve loop attaches to the whole agent group, not to the database API. System boundary encloses both base context and overlay.
Brand source and licence notices retained in ../components-v3/brand-icons/.
Render: python3 render.py; sips -s format png shared-context-capabilities-v4.svg --out shared-context-capabilities-v4.png.
''')
print(P/'shared-context-capabilities-v4.svg')
