"""Omni — Claude-CLI-style workflow console (Starlette + uvicorn, no new deps).

A big scrolling transcript that streams every agent line and state event over
SSE (reads like a CLI), a small chat box at the bottom to launch runs, a sidebar
of runs/tasks/agents, and a live token/cost readout. Backed by the workflow
engine; demo mode uses mock agents in a throwaway repo for an instant, free run.

    omnigent web [--port 8770]
"""
from __future__ import annotations

from starlette.applications import Starlette
from starlette.responses import HTMLResponse, JSONResponse
from starlette.routing import Route

from . import __version__
from .core import list_harnesses
from .workflow.webapi import routes as workflow_routes


_profile: str | None = None  # set by serve(); None = today's behavior (all harnesses)


async def index(_r):
    return HTMLResponse(PAGE)


async def harnesses(_r):
    return JSONResponse({
        "version": __version__,
        "harnesses": {n: {"available": h.available} for n, h in list_harnesses(_profile).items()},
    })


app = Starlette(routes=[
    Route("/", index),
    Route("/harnesses", harnesses),
    *workflow_routes,
])


def serve(host: str = "127.0.0.1", port: int = 8770, profile: str | None = None):
    import uvicorn
    global _profile
    _profile = profile
    print(f"Omni console -> http://{host}:{port}" + (f"  (profile: {profile})" if profile else ""))
    uvicorn.run(app, host=host, port=port, log_level="warning")


PAGE = r"""<!doctype html>
<html lang="en"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Omni</title>
<style>
:root{
  --bg:#1b1a17; --panel:#211f1c; --elev:#2a2723; --line:rgba(255,255,255,.08); --line2:rgba(255,255,255,.13);
  --ink:#eae7e1; --muted:#a29b8f; --subtle:#8f887c;
  --accent:#d97757; --accent-soft:rgba(217,119,87,.15);
  --claude:#d97757; --codex:#82c996; --grok:#6ba3e8; --omni:#d0c3b1; --sys:#8a8478;
  --ok:#82c996; --active:#6ba3e8; --warn:#e0a458; --bad:#e0645a;
  --mono:ui-monospace,"Cascadia Code","JetBrains Mono",Consolas,monospace;
  font-family:ui-sans-serif,system-ui,-apple-system,"Segoe UI",sans-serif;
}
*{box-sizing:border-box;margin:0}
html,body{height:100%}
body{background:var(--bg);color:var(--ink);font-size:14px;line-height:1.5;overflow:hidden}
button{font:inherit;color:inherit;cursor:pointer;border:0;background:none}
input,textarea{font:inherit;color:var(--ink);background:#141310;border:1px solid var(--line2);border-radius:8px;padding:9px 11px;width:100%}
input:focus,textarea:focus{outline:none;border-color:var(--accent)}
button:focus-visible,.run-item:focus-visible,input:focus-visible,textarea:focus-visible{outline:2px solid var(--accent);outline-offset:2px}
::-webkit-scrollbar{width:10px;height:10px}
::-webkit-scrollbar-thumb{background:#38342e;border-radius:6px;border:2px solid var(--bg)}

.app{display:grid;grid-template-columns:252px minmax(0,1fr);height:100%}
nav{border-right:1px solid var(--line);background:var(--panel);display:flex;flex-direction:column;overflow:hidden}
.brand{display:flex;align-items:center;gap:8px;padding:14px 16px;font-weight:600;border-bottom:1px solid var(--line)}
.brand .glyph{width:22px;height:22px;border-radius:6px;background:var(--elev);border:1px solid var(--line2);display:grid;place-items:center;color:var(--accent);font-weight:700}
.brand .ver{margin-left:auto;color:var(--subtle);font-size:11px;font-weight:400}
.nav-scroll{flex:1;overflow:auto;padding:12px 10px}
.side-label{font-size:10.5px;letter-spacing:.07em;text-transform:uppercase;color:var(--subtle);margin:14px 6px 6px}
.run-item{padding:8px 10px;border-radius:8px;cursor:pointer;display:flex;gap:8px;align-items:center}
.run-item:hover{background:var(--elev)} .run-item.on{background:var(--accent-soft)}
.run-item .goal{overflow:hidden;text-overflow:ellipsis;white-space:nowrap;font-size:13px}
.dot{font-size:11px;line-height:1}
.task-row{display:flex;gap:8px;align-items:center;padding:5px 8px;font-size:12px;color:var(--muted)}
.task-row .agent{font-family:var(--mono);font-size:11px}
.agent-row{display:flex;gap:8px;align-items:center;padding:5px 8px;font-size:12.5px}
.agent-chip{font-family:var(--mono);font-size:11px;padding:1px 6px;border-radius:5px;background:var(--elev);border:1px solid var(--line)}

main{display:flex;flex-direction:column;min-width:0;min-height:0}
.topbar{display:flex;align-items:center;gap:12px;padding:10px 18px;border-bottom:1px solid var(--line);background:var(--panel)}
.topbar .title{font-size:13.5px;font-weight:600;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.topbar .spacer{flex:1}
.status{display:inline-flex;align-items:center;gap:6px;font-size:12px;color:var(--muted)}
.cost{font-family:var(--mono);font-size:12px;color:var(--muted);white-space:nowrap}
.cost b{color:var(--ink);font-weight:600}
.btn{padding:7px 13px;border-radius:8px;font-size:13px;font-weight:600;border:1px solid var(--line2);color:var(--ink)}
.btn:hover{border-color:#4a453e}
.btn.primary{background:var(--accent);border-color:transparent;color:#1b1a17}
.btn.sm{padding:5px 10px;font-size:12px;font-weight:500}
.btn.ghost{border-color:var(--line2);color:var(--muted)}

.transcript{flex:1;overflow:auto;padding:16px 20px;font-family:var(--mono);font-size:12.5px;line-height:1.65}
.ln{display:flex;gap:10px;padding:1px 0;white-space:pre-wrap;word-break:break-word}
.ln .who{flex:0 0 62px;text-align:right;color:var(--subtle)}
.ln .txt{flex:1;min-width:0}
.who.claude{color:var(--claude)} .who.codex{color:var(--codex)} .who.grok{color:var(--grok)}
.who.omni{color:var(--accent)} .who.system{color:var(--bad)} .who.sys{color:var(--sys)}
.ev{color:var(--muted)} .ev .g{margin-right:7px}
.ev.ok .g{color:var(--ok)} .ev.warn .g{color:var(--warn)} .ev.bad .g{color:var(--bad)}
.ev.active .g{color:var(--active)} .ev.accent .g{color:var(--accent)}
.cursor{color:var(--accent);animation:blink 1.1s steps(1) infinite}
@keyframes blink{50%{opacity:0}}
.empty{color:var(--subtle);text-align:center;margin-top:16vh;font-family:inherit}
.empty h3{color:var(--muted);font-weight:600;margin-bottom:8px}

.composer{border-top:1px solid var(--line);background:var(--panel);padding:12px 16px}
.composer .opts{display:flex;gap:10px;align-items:center;margin-bottom:8px}
.composer .opts input[type=text]{flex:1;padding:7px 10px;font-size:12.5px;font-family:var(--mono)}
.composer .box{display:flex;gap:10px;align-items:flex-end}
.composer textarea{min-height:44px;max-height:160px;resize:none}
.toggle{display:inline-flex;align-items:center;gap:6px;font-size:12px;color:var(--muted);white-space:nowrap;cursor:pointer}
.hint{color:var(--subtle);font-size:11px;margin-top:6px}
</style></head>
<body>
<div class="app">
  <nav>
    <div class="brand"><span class="glyph">&#937;</span> omni <span class="ver" id="ver"></span></div>
    <div class="nav-scroll">
      <button class="btn primary sm" style="width:100%" id="new-btn">+ New Run</button>
      <div class="side-label">Runs</div>
      <div id="runs"></div>
      <div class="side-label">Tasks</div>
      <div id="tasks"><div class="task-row">select a run</div></div>
      <div class="side-label">Agents</div>
      <div id="agents"></div>
      <div class="side-label">Knowledge</div>
      <div id="knowledge"><div class="task-row" style="color:var(--subtle)">—</div></div>
    </div>
  </nav>
  <main>
    <div class="topbar">
      <span class="title" id="title">Omni workflow console</span>
      <span class="status" id="run-status"></span>
      <span class="spacer"></span>
      <button class="btn sm ghost hidden" id="approve-btn">Approve &amp; finish</button>
      <span class="cost" id="cost">&#8593; 0 &#8595; 0 &middot; $0.00</span>
    </div>
    <div class="transcript" id="transcript">
      <div class="empty" id="empty"><h3>No run selected</h3>
        Type a goal below and the agents get to work — you'll watch them stream here, CLI-style.</div>
    </div>
    <div class="composer">
      <div class="opts">
        <input type="text" id="project" placeholder="git repo path (blank + demo = throwaway repo)">
        <label class="toggle"><input type="checkbox" id="mock" checked style="width:auto"> demo (mock agents)</label>
      </div>
      <div class="box">
        <textarea id="goal" placeholder="Give the agents a goal…  (Enter to run, Shift+Enter for newline)"></textarea>
        <button class="btn primary" id="send">Run</button>
      </div>
      <div class="hint" id="hint">Demo mode runs mock agents in a throwaway repo — instant &amp; free. Uncheck to drive your real CLIs on a real repo.</div>
    </div>
  </main>
</div>
<script>
const $=s=>document.querySelector(s);
const api=(u,o)=>fetch(u,o).then(r=>r.ok?r.json():Promise.reject(r.status)).catch(()=>null);
const S={sel:null, es:null, poll:null, harnesses:{}};

const ACOLOR={claude:'claude',codex:'codex',grok:'grok',omni:'omni',system:'system',sys:'sys'};
const EVMAP={
  RUN_CREATED:['◇','ev','run created'], AGENT_ASSIGNED:['▸','ev','assigned'],
  TASK_STARTED:['●','ev active','started'], COMMIT_CREATED:['◆','ev ok','commit'],
  REVIEW_STARTED:['◇','ev','review'], REVIEW_COMPLETED:['◈','ev','review done'],
  CHANGES_REQUESTED:['⚠','ev warn','changes requested'], REVISION_STARTED:['↻','ev warn','revising'],
  TASK_APPROVED:['✓','ev ok','approved'], TASK_INTEGRATED:['⇢','ev ok','integrated'],
  INTEGRATION_CONFLICT:['✕','ev bad','conflict'], VALIDATION_COMPLETED:['▣','ev ok','validation'],
  RUN_READY:['★','ev accent','ready for review'], RUN_APPROVED:['✓','ev ok','run approved'],
  TASK_FAILED:['✕','ev bad','failed'], REVISION:['↻','ev warn','revision'],
  CONTEXT_RETRIEVED:['◇','ev','knowledge'], MEMORY_WRITTEN:['✎','ev ok','memory saved'],
};
const STATUSDOT={PLANNING:'◇',RUNNING:'●',REVIEWING:'◈',INTEGRATING:'⇢',
  WAITING_FOR_USER:'★',COMPLETED:'✓',FAILED:'✕',CANCELLED:'✕',
  PLANNED:'○',READY:'◌',REVIEW_READY:'◈',CHANGES_REQUESTED:'⚠',APPROVED:'✓'};
const esc=s=>(s||'').replace(/[&<>]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;'}[c]));

function line(html){const t=$('#transcript');const atBottom=t.scrollHeight-t.scrollTop-t.clientHeight<60;
  const d=document.createElement('div');d.className='ln';d.innerHTML=html;t.appendChild(d);
  if(atBottom)t.scrollTop=t.scrollHeight;}
function renderFeed(item){
  if(item.type==='output'){
    const who=ACOLOR[item.agent]||'sys';
    line(`<span class="who ${who}">${esc(item.agent||'')}</span><span class="txt">${esc(item.line||'')}</span>`);
  } else {
    const [g,cls,label]=EVMAP[item.event]||['·','ev',item.event.toLowerCase()];
    const tsk=item.payload&&item.payload.commit?(' '+String(item.payload.commit).slice(0,8)):'';
    const findings=(item.payload&&item.payload.findings||[]).slice(0,2).map(f=>' — '+f).join('');
    const cnt=(item.event==='CONTEXT_RETRIEVED'&&item.payload&&item.payload.count)?(' · '+item.payload.count+' sources'):'';
    line(`<span class="who sys"></span><span class="txt ${cls}"><span class="g">${g}</span>${esc(label)}${item.agent?(' · '+esc(item.agent)):''}${esc(tsk)}${esc(cnt)}${esc(findings)}</span>`);
  }
}

async function loadState(){
  const h=await api('/harnesses');if(!h){$('#ver').textContent='offline';return;}
  S.harnesses=h.harnesses;$('#ver').textContent='v'+h.version;
  $('#agents').innerHTML=Object.entries(h.harnesses).map(([n,x])=>
    `<div class="agent-row"><span class="dot" style="color:${x.available?'var(--ok)':'var(--subtle)'}">●</span>
      <span class="agent-chip" style="color:var(--${n})">${n}</span>
      <span style="color:var(--subtle);font-size:11px">${x.available?'available':'offline'}</span></div>`).join('');
  const st=await api('/api/state');if(!st)return; renderRuns(st.runs);
  const kn=st.knowledge||{}; const kEl=$('#knowledge');
  if(kEl) kEl.innerHTML = kn.enabled
    ? `<div class="task-row"><span class="dot" style="color:var(--ok)">●</span>${kn.documents||0} docs · ${(kn.sources||[]).length} sources</div>`
    : `<div class="task-row" style="color:var(--subtle)">disabled</div>`;
}
function renderRuns(runs){
  $('#runs').innerHTML=runs.length?runs.map(r=>{
    const dot=STATUSDOT[r.status]||'○';
    const col=r.status==='COMPLETED'||r.status==='WAITING_FOR_USER'?'var(--ok)':r.status==='FAILED'?'var(--bad)':'var(--active)';
    return `<div class="run-item ${S.sel===r.id?'on':''}" data-id="${r.id}">
      <span class="dot" style="color:${col}">${dot}</span><span class="goal">${esc(r.goal)}</span></div>`;
  }).join(''):'<div class="task-row">no runs yet</div>';
  document.querySelectorAll('.run-item').forEach(el=>el.onclick=()=>selectRun(el.dataset.id));
}

async function selectRun(id){
  S.sel=id; if(S.es)S.es.close(); if(S.poll)clearInterval(S.poll);
  document.querySelectorAll('.run-item').forEach(e=>e.classList.toggle('on',e.dataset.id===id));
  $('#empty')&&$('#empty').remove();
  $('#transcript').innerHTML='';
  await refreshSnapshot();
  // live stream (replays this session's feed from the start, then tails)
  S.es=new EventSource('/api/runs/'+id+'/stream');
  S.es.addEventListener('feed',e=>renderFeed(JSON.parse(e.data)));
  S.es.addEventListener('done',e=>{refreshSnapshot();});
  S.poll=setInterval(refreshSnapshot,1600);
}

async function refreshSnapshot(){
  if(!S.sel)return; const s=await api('/api/runs/'+S.sel); if(!s||!s.run)return;
  $('#title').textContent=s.run.goal;
  const dot=STATUSDOT[s.run.status]||'○';
  $('#run-status').innerHTML=`<span class="dot">${dot}</span>${s.run.status.replace(/_/g,' ').toLowerCase()}`;
  const su=s.summary;
  $('#cost').innerHTML=`&#8593; ${fmt(su.tokens_in)} &#8595; ${fmt(su.tokens_out)} &middot; <b>$${(su.cost_usd||0).toFixed(4)}</b>`;
  $('#tasks').innerHTML=s.tasks.length?s.tasks.map(t=>{
    const a=(t.assignments[0]||{}).agent||t.assigned_agent||'—';
    return `<div class="task-row"><span class="dot">${STATUSDOT[t.status]||'○'}</span>
      <span style="flex:1;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">${esc(t.title)}</span>
      <span class="agent" style="color:var(--${a}, var(--muted))">${esc(a)}</span></div>`;
  }).join(''):'<div class="task-row">no tasks</div>';
  $('#approve-btn').classList.toggle('hidden', s.run.status!=='WAITING_FOR_USER');
}
function fmt(n){n=n||0;return n>=1000?(n/1000).toFixed(1)+'k':n;}

async function send(){
  const goal=$('#goal').value.trim(); if(!goal)return;
  $('#send').disabled=true;
  const body={goal, project_path:$('#project').value.trim(), mock:$('#mock').checked};
  const r=await api('/api/runs',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
  $('#send').disabled=false;
  if(!r){alert('server unreachable');return;}
  if(r.error){alert(r.error);return;}
  $('#goal').value='';
  await loadState(); selectRun(r.id);
}

$('#send').onclick=send;
$('#new-btn').onclick=()=>{$('#goal').focus();};
$('#approve-btn').onclick=async()=>{await fetch('/api/runs/'+S.sel+'/approve',{method:'POST'});refreshSnapshot();};
$('#goal').addEventListener('keydown',e=>{if(e.key==='Enter'&&!e.shiftKey){e.preventDefault();send();}});
loadState();
</script>
</body></html>"""
