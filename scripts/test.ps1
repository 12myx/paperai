# Run backend tests, frontend typecheck/build and browser QA.
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot

Write-Host "== Backend tests ==" -ForegroundColor Cyan
Push-Location "$root\backend"; python -m pytest tests -q; Pop-Location

Write-Host "== Frontend build ==" -ForegroundColor Cyan
Push-Location "$root\frontend"; npm.cmd run build; Pop-Location

Write-Host "== Browser QA (requires a running server on :8000) ==" -ForegroundColor Cyan
Push-Location "$root\qa"; node run.mjs; Pop-Location
