# Try multiple methods to find and kill the process
$pid = 1520

# Method 1: WMI
Write-Host "=== WMI Query ==="
$p = Get-CimInstance -ClassName Win32_Process -Filter "ProcessId = $pid" -ErrorAction SilentlyContinue
if ($p) {
    Write-Host "Found via WMI: $($p.Name) (PID: $($p.ProcessId))"
    Write-Host "CommandLine: $($p.CommandLine)"
    Write-Host "ParentProcessId: $($p.ParentProcessId)"
    Write-Host "Owner: $($p.GetOwner().User)"
} else {
    Write-Host "No WMI entry for PID $pid"
}

# Method 2: Try closing via netsh (doesn't work for TCP)
# Method 3: Check if it's a service
Write-Host "`n=== Checking Service ==="
$svc = Get-WmiObject -Class Win32_Service -Filter "ProcessId = $pid" -ErrorAction SilentlyContinue
if ($svc) {
    Write-Host "Found service: $($svc.Name)"
}

# Method 4: Try to use Tcpip settings
Write-Host "`n=== TCP Connection Details ==="
Get-NetTCPConnection -LocalPort 8000 | Format-List
