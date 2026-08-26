# Launch Omni — the all-in-one console (Cloud + Local modes in one system).
# Ensures Docker/Ollama (for local-mode models), starts the console, opens it.
$ErrorActionPreference = 'SilentlyContinue'
$root = Split-Path -Parent $MyInvocation.MyCommand.Definition
$exe  = Join-Path $root '.venv\Scripts\omnigent.exe'
$port = 8770
$url  = "http://127.0.0.1:$port"

function Test-Port($p) { $c = New-Object Net.Sockets.TcpClient; try { $c.Connect('127.0.0.1', $p); return $c.Connected } catch { return $false } finally { $c.Close() } }
function Test-Engine { docker info --format '{{.ServerVersion}}' 2>$null }

# Docker + Ollama — local mode runs its models here (cloud mode doesn't need them, but
# starting Ollama now keeps local mode instant).
if (-not (Test-Engine)) {
    $dd = "C:\Program Files\Docker\Docker\Docker Desktop.exe"
    if (Test-Path $dd) { Start-Process $dd }
    for ($i = 0; $i -lt 40 -and -not (Test-Engine); $i++) { Start-Sleep -Seconds 3 }
}
if ((Test-Engine) -and -not (docker ps --format '{{.Names}}' | Select-String 'ollama-backend')) {
    if (Test-Path 'C:\LocalAI\Hermes3\docker-compose.yml') {
        Push-Location 'C:\LocalAI\Hermes3'; docker compose up -d ollama 2>$null | Out-Null; Pop-Location
    }
}

# env so the local agents resolve + use the right model
$env:OLLAMA_API_BASE = 'http://localhost:11434'   # aider (litellm) + opencode ollama provider
$env:GOOSE_PROVIDER = 'ollama'
$env:GOOSE_MODEL    = 'qwen3:14b'
$env:PATH = "$env:PATH;C:\Users\losth\.local\bin;C:\Users\losth\AppData\Roaming\npm;C:\Users\losth\AppData\Roaming\Python\Python310\Scripts"

if (-not (Test-Path $exe)) {
    Add-Type -AssemblyName System.Windows.Forms
    [System.Windows.Forms.MessageBox]::Show("Omni isn't installed at:`n$exe","Omni") | Out-Null
    return
}
if (-not (Test-Port $port)) {
    Start-Process -FilePath $exe -ArgumentList 'web', '--port', $port -WindowStyle Hidden
    for ($i = 0; $i -lt 20 -and -not (Test-Port $port); $i++) { Start-Sleep -Seconds 1 }
}
Start-Process $url
