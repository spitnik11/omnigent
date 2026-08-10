"""Minimal local web UI for Omnigent.

Starlette + uvicorn (both already installed via crewai — no new deps). One page:
task box, harness picker (auto/claude/grok/codex), project dir, Run. POST /run
executes through the same dispatch the CLI uses and returns JSON.

    omnigent web [--port 8770]
"""
from __future__ import annotations

from starlette.applications import Starlette
from starlette.concurrency import run_in_threadpool
from starlette.responses import HTMLResponse, JSONResponse
from starlette.routing import Route

from . import __version__
from .cli import _dispatch
from .core import list_harnesses

PAGE = """<!doctype html>
<html lang="en"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Omnigent</title>
<style>
  :root {
    --bg:#0e0f11; --panel:#17181b; --line:#26282d; --fg:#e8e9ea; --muted:#8b8e94;
    --accent:#5b8cff; --ok:#3fb950; --bad:#f85149; --radius:10px;
    font-family: ui-sans-serif, -apple-system, "Segoe UI", Roboto, sans-serif;
  }
  * { box-sizing:border-box; }
  body { margin:0; background:var(--bg); color:var(--fg); line-height:1.5; }
  .wrap { max-width:860px; margin:0 auto; padding:32px 20px 64px; }
  header { display:flex; align-items:baseline; gap:12px; margin-bottom:24px; }
  h1 { font-size:20px; font-weight:650; letter-spacing:-.01em; margin:0; }
  .ver { color:var(--muted); font-size:12px; }
  .card { background:var(--panel); border:1px solid var(--line); border-radius:var(--radius); padding:18px; }
  label { display:block; font-size:12px; color:var(--muted); margin:0 0 6px; }
  textarea, input, select {
    width:100%; background:#0e0f11; border:1px solid var(--line); color:var(--fg);
    border-radius:8px; padding:10px 12px; font:inherit; font-size:14px;
  }
  textarea { resize:vertical; min-height:84px; }
  textarea:focus, input:focus, select:focus { outline:none; border-color:var(--accent); }
  .row { display:grid; grid-template-columns:1fr 2fr; gap:12px; margin-top:12px; }
  .bar { display:flex; align-items:center; gap:12px; margin-top:14px; }
  button {
    background:var(--accent); color:#fff; border:0; border-radius:8px;
    padding:10px 18px; font:inherit; font-weight:600; font-size:14px; cursor:pointer;
  }
  button:disabled { opacity:.5; cursor:default; }
  .status { font-size:13px; color:var(--muted); }
  .status b { font-weight:600; }
  .ok { color:var(--ok); } .bad { color:var(--bad); }
  pre {
    margin:16px 0 0; background:#0b0c0e; border:1px solid var(--line); border-radius:8px;
    padding:14px; white-space:pre-wrap; word-break:break-word; font-size:13px;
    font-family: ui-monospace, "Cascadia Code", Consolas, monospace; min-height:60px;
    max-height:52vh; overflow:auto;
  }
  .hint { color:var(--muted); font-size:12px; margin-top:10px; }
</style></head>
<body><div class="wrap">
  <header><h1>Omnigent</h1><span class="ver" id="ver"></span></header>
  <div class="card">
    <label for="task">Task <span style="opacity:.6">(prefix <code>@grok</code> to force a harness)</span></label>
    <textarea id="task" placeholder="e.g. review this repo and list the top 3 risks"></textarea>
    <div class="row">
      <div><label for="harness">Harness</label><select id="harness"></select></div>
      <div><label for="project">Project directory</label><input id="project" placeholder="(current dir)"></div>
    </div>
    <div class="bar">
      <button id="run">Run</button>
      <span class="status" id="status">idle</span>
    </div>
    <pre id="out"></pre>
    <div class="hint">Runs block until the agent finishes (up to 30 min). One task at a time.</div>
  </div>
</div>
<script>
const $ = id => document.getElementById(id);
fetch('/harnesses').then(r=>r.json()).then(d=>{
  $('ver').textContent = 'v' + d.version + ' · ' + d.engine;
  const sel = $('harness');
  sel.innerHTML = '<option value="auto">auto (router)</option>';
  for (const [name, ok] of Object.entries(d.harnesses)) {
    const o = document.createElement('option');
    o.value = name; o.textContent = name + (ok ? '' : ' (unavailable)'); o.disabled = !ok;
    sel.appendChild(o);
  }
});
async function run() {
  const task = $('task').value.trim();
  if (!task) { $('status').textContent = 'enter a task'; return; }
  $('run').disabled = true; $('status').innerHTML = '<b>running…</b>'; $('out').textContent = '';
  const t0 = Date.now();
  try {
    const r = await fetch('/run', {method:'POST', headers:{'Content-Type':'application/json'},
      body: JSON.stringify({task, harness: $('harness').value, project: $('project').value.trim()})});
    const d = await r.json();
    if (d.error) { $('status').innerHTML = '<span class="bad">'+d.error+'</span>'; }
    else {
      const cls = d.ok ? 'ok' : 'bad';
      $('status').innerHTML = '▶ <b>'+d.chosen+'</b> · '+d.seconds+'s · <span class="'+cls+'">'+(d.ok?'ok':'FAILED')+'</span>';
      $('out').textContent = d.output || '(no output)';
    }
  } catch (e) {
    $('status').innerHTML = '<span class="bad">'+e+'</span>';
  } finally { $('run').disabled = false; }
}
$('run').addEventListener('click', run);
$('task').addEventListener('keydown', e => { if ((e.ctrlKey||e.metaKey) && e.key==='Enter') run(); });
</script>
</body></html>"""


async def index(_request):
    return HTMLResponse(PAGE)


async def harnesses(_request):
    from .cli import _HAVE_FLOW
    return JSONResponse({
        "version": __version__,
        "engine": "CrewAI Flow" if _HAVE_FLOW else "direct core",
        "harnesses": {n: h.available for n, h in list_harnesses().items()},
    })


async def run_task(request):
    data = await request.json()
    task = (data.get("task") or "").strip()
    if not task:
        return JSONResponse({"error": "empty task"}, status_code=400)
    harness = data.get("harness") or "auto"
    project = (data.get("project") or "").strip() or None
    chosen, ok, output, seconds = await run_in_threadpool(
        _dispatch, task, None if harness == "auto" else harness, project, 1800
    )
    return JSONResponse({"chosen": chosen, "ok": ok, "output": output, "seconds": round(seconds, 1)})


app = Starlette(routes=[
    Route("/", index),
    Route("/harnesses", harnesses),
    Route("/run", run_task, methods=["POST"]),
])


def serve(host: str = "127.0.0.1", port: int = 8770):
    import uvicorn
    print(f"Omnigent web UI → http://{host}:{port}")
    uvicorn.run(app, host=host, port=port, log_level="warning")
