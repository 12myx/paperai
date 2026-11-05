param(
  [string]$EnvFile = "$PSScriptRoot\.env.production"
)

$ErrorActionPreference = "Stop"
if (-not (Test-Path $EnvFile)) {
  throw "Missing $EnvFile. Copy deploy/.env.production.example and set a strong secret."
}

Get-Content $EnvFile | ForEach-Object {
  $line = $_.Trim()
  if (-not $line -or $line.StartsWith("#")) { return }
  $index = $line.IndexOf("=")
  if ($index -lt 1) { return }
  $key = $line.Substring(0, $index).Trim()
  $value = $line.Substring($index + 1).Trim()
  [Environment]::SetEnvironmentVariable($key, $value, "Process")
}

$root = Split-Path -Parent $PSScriptRoot
Set-Location (Join-Path $root "backend")
Write-Host "Starting PaperLens in $env:PAPERLENS_ENVIRONMENT mode on 0.0.0.0:8000"
python run.py
