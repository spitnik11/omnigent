# Omnigent tasks — run `just` (or `just --list`) to see them.
# Windows/PowerShell flavored (this machine). `just` = one entrypoint per repo.
set windows-shell := ["powershell.exe", "-NoLogo", "-Command"]

# show the task list
default:
    @just --list

# create the venv and install editable (+ crewai)
setup:
    python -m venv .venv
    .venv\Scripts\python.exe -m pip install -e .

# fast core checks — no crewai needed
test:
    .venv\Scripts\python.exe test_router.py
    .venv\Scripts\python.exe -m omnigent.harness

# which harnesses are available
list:
    .venv\Scripts\omnigent.exe list

# launch the local web UI (just web / just web 8888)
web port="8770":
    .venv\Scripts\omnigent.exe web --port {{port}}

# one-off task: just run "@grok say hi"
run task:
    .venv\Scripts\omnigent.exe run "{{task}}"
