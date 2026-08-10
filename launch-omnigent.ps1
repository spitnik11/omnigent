# Launch Omnigent: start the web UI (if not already running), then open the browser.
$ErrorActionPreference = 'SilentlyContinue'
$root = Split-Path -Parent $MyInvocation.MyCommand.Definition
$exe  = Join-Path $root '.venv\Scripts\omnigent.exe'
$port = 8770
$url  = "http://127.0.0.1:$port"

function Test-Port($p) {
    $c = New-Object Net.Sockets.TcpClient
    try { $c.Connect('127.0.0.1', $p); return $c.Connected } catch { return $false } finally { $c.Close() }
}

if (-not (Test-Path $exe)) {
    Add-Type -AssemblyName System.Windows.Forms
    [System.Windows.Forms.MessageBox]::Show(
        "Omnigent isn't installed yet.`n`nExpected: $exe`n`nFrom the project folder run:`n  python -m venv .venv`n  .venv\Scripts\python -m pip install -e .",
        "Omnigent") | Out-Null
    return
}

if (-not (Test-Port $port)) {
    Start-Process -FilePath $exe -ArgumentList 'web', '--port', $port -WindowStyle Hidden
    for ($i = 0; $i -lt 20 -and -not (Test-Port $port); $i++) { Start-Sleep -Milliseconds 300 }
}
Start-Process $url
