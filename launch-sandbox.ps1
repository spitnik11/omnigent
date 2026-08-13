# Omni Local Sandbox launcher — ensure Ollama (Docker) is up, start the local-only
# Omni console (aider/opencode/goose), and open it in the browser.
$ErrorActionPreference = 'SilentlyContinue'
$root = Split-Path -Parent $MyInvocation.MyCommand.Definition
$url  = 'http://localhost:8771'
$exe  = Join-Path $root '.venv\Scripts\omnigent.exe'

function Test-Engine { docker info --format '{{.ServerVersion}}' 2>$null }
function Test-Url { param($u) try { (Invoke-WebRequest $u -UseBasicParsing -TimeoutSec 3).StatusCode -eq 200 } catch { $false } }

# 1. Docker engine (the local coding model runs in Ollama, in Docker)
if (-not (Test-Engine)) {
    $dd = "C:\Program Files\Docker\Docker\Docker Desktop.exe"
    if (Test-Path $dd) { Start-Process $dd }
    for ($i = 0; $i -lt 40 -and -not (Test-Engine); $i++) { Start-Sleep -Seconds 3 }
}
# 2. Ollama container (reuse the Hermes stack's ollama-backend)
if (Test-Engine -and -not (docker ps --format '{{.Names}}' | Select-String 'ollama-backend')) {
    if (Test-Path 'C:\LocalAI\Hermes3\docker-compose.yml') {
        Push-Location 'C:\LocalAI\Hermes3'; docker compose up -d ollama 2>$null | Out-Null; Pop-Location
    }
}
# 3. env for the local agents (inherited by the console + the CLIs it spawns)
$env:GOOSE_PROVIDER = 'ollama'
$env:GOOSE_MODEL    = 'qwen3:14b'
$env:PATH = "$env:PATH;C:\Users\losth\.local\bin;C:\Users\losth\AppData\Roaming\npm;C:\Users\losth\AppData\Roaming\Python\Python310\Scripts"

# 4. start the local-profile console if not already up
if (-not (Test-Url $url)) {
    if (-not (Test-Path $exe)) {
        Add-Type -AssemblyName System.Windows.Forms
        [System.Windows.Forms.MessageBox]::Show("Omni isn't installed at:`n$exe","Omni Local Sandbox") | Out-Null
        return
    }
    Start-Process -FilePath $exe -ArgumentList 'web', '--port', '8771', '--profile', 'local' -WindowStyle Hidden
    for ($i = 0; $i -lt 20 -and -not (Test-Url $url); $i++) { Start-Sleep -Seconds 2 }
}
Start-Process $url
