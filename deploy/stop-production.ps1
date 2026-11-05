$conn = Get-NetTCPConnection -LocalPort 8000 -State Listen -ErrorAction SilentlyContinue | Select-Object -First 1
if ($conn) {
  Stop-Process -Id $conn.OwningProcess -Force
  Write-Host "Stopped PaperLens on port 8000 (PID $($conn.OwningProcess))"
} else {
  Write-Host "No listener on port 8000"
}
