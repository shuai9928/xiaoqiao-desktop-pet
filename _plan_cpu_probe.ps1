$c = Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -like '*pet.py*' }
if (-not $c) { Write-Output 'NO_PET_PROCESS'; exit }
foreach ($proc in $c) {
    Write-Output ("PID=" + $proc.ProcessId + " NAME=" + $proc.Name)
    Write-Output ("  CMD=" + $proc.CommandLine)
    $p1 = Get-Process -Id $proc.ProcessId
    $cpu1 = $p1.CPU
    $t1 = Get-Date
    Start-Sleep -Seconds 10
    $p2 = Get-Process -Id $proc.ProcessId
    $dt = ((Get-Date) - $t1).TotalSeconds
    $dcpu = $p2.CPU - $cpu1
    Write-Output ("  CPU10s=" + [Math]::Round($dcpu, 2) + "s pct_of_core=" + [Math]::Round(100 * $dcpu / $dt, 1) + "% RSS_MB=" + [Math]::Round($p2.WorkingSet64 / 1MB, 1))
}
