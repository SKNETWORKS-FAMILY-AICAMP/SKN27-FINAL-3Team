# Local dev launcher: opens one window each for backend, agent-worker,
# file-scan-worker, and the frontend. Run this instead of starting each
# process by hand every time.
#
# Usage:
#   .\dev-local.ps1
#
# Stop everything by closing the opened windows (or Ctrl+C in each).

$ErrorActionPreference = "Stop"
$root = $PSScriptRoot

function Start-Dev($title, $workDir, $command) {
    Start-Process powershell -ArgumentList @(
        "-NoExit",
        "-Command",
        "cd `"$workDir`"; `$env:DJANGO_ENV_FILE='.env'; `$Host.UI.RawUI.WindowTitle = '$title'; $command"
    )
}

Write-Host "Starting backend (port 8010)..."
Start-Dev "backend" $root "python backend\manage.py runserver 8010"

Write-Host "Starting agent-worker..."
Start-Dev "agent-worker" $root "python backend\manage.py process_agent_work_items --loop"

Write-Host "Starting file-scan-worker..."
Start-Dev "file-scan-worker" $root "python backend\manage.py process_uploaded_file_scans --loop"

Write-Host "Starting frontend (vite)..."
Start-Dev "frontend" "$root\app\web" "npm run dev"

Write-Host ""
Write-Host "4 windows opened: backend / agent-worker / file-scan-worker / frontend."
Write-Host "Close each window (or Ctrl+C inside it) to stop that process."
