# Start PaperLens AI for local development (Windows PowerShell)
# Usage:  .\scripts\dev.ps1
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

Write-Host "Starting backend on http://127.0.0.1:8000 ..." -ForegroundColor Cyan
$backend = Start-Process -FilePath "python" -ArgumentList "run.py" -WorkingDirectory "$root\backend" -PassThru -WindowStyle Hidden

Write-Host "Starting frontend on http://127.0.0.1:5173 ..." -ForegroundColor Cyan
Push-Location "$root\frontend"
if (-not (Test-Path "node_modules")) { npm.cmd install }
npm.cmd run dev
Pop-Location

if (-not $backend.HasExited) { Stop-Process -Id $backend.Id }
