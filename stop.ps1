# ChiefMailVault - stop server on configured port
$Port = if ($env:CMV_PORT) { [int]$env:CMV_PORT } else { 8088 }

function Get-PortListenerPids {
    param([int]$TargetPort)
    $pids = [System.Collections.Generic.HashSet[int]]::new()
    try {
        $conns = Get-NetTCPConnection -LocalPort $TargetPort -ErrorAction SilentlyContinue |
            Where-Object { $_.State -eq 'Listen' }
        foreach ($c in $conns) { [void]$pids.Add($c.OwningProcess) }
    } catch { }
    $netstat = netstat -ano | Select-String ":$TargetPort\s+.*LISTENING"
    foreach ($line in $netstat) {
        if ($line -match '\s+(\d+)\s*$') { [void]$pids.Add([int]$Matches[1]) }
    }
    return @($pids | Where-Object { $_ -gt 0 -and (Get-Process -Id $_ -ErrorAction SilentlyContinue) })
}

$pids = Get-PortListenerPids -TargetPort $Port
if (-not $pids) {
    Write-Host "No ChiefMailVault process found on port $Port." -ForegroundColor Yellow
    exit 0
}

foreach ($procId in $pids) {
    $proc = Get-Process -Id $procId -ErrorAction SilentlyContinue
    Write-Host "Stopping PID $procId ($($proc.ProcessName))..." -ForegroundColor Yellow
    cmd /c "taskkill /F /PID $procId /T" 2>$null | Out-Null
}

Start-Sleep -Seconds 2
Write-Host "Done." -ForegroundColor Green
