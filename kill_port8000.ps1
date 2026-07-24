$conn = Get-NetTCPConnection -LocalPort 8000 -ErrorAction SilentlyContinue
if ($conn) {
    Write-Host "Found process on port 8000: PID $($conn.OwningProcess)"
    try {
        $process = Get-Process -Id $conn.OwningProcess -ErrorAction Stop
        Write-Host "Process name: $($process.ProcessName)"
        Stop-Process -Id $conn.OwningProcess -Force
        Write-Host "Process $($conn.OwningProcess) killed successfully."
    } catch {
        Write-Host "Cannot find/stop process $($conn.OwningProcess): $_"
    }
} else {
    Write-Host "No process found on port 8000."
}
