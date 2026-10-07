$ErrorActionPreference = 'SilentlyContinue'
$log = (Join-Path $PSScriptRoot 'soak_monitor.log')
$p = Get-CimInstance Win32_Process -Filter "Name='pythonw.exe' or Name='DesktopPet.exe'" |
     Where-Object { $_.CommandLine -like '*pet.py*' -or $_.Name -eq 'DesktopPet.exe' } |
     Select-Object -First 1
if ($p) {
  $proc = Get-Process -Id $p.ProcessId
  $line = '{0},{1},{2:N0},{3},{4:N1}' -f (Get-Date -Format 'yyyy-MM-dd HH:mm:ss'), $p.Name, ($proc.WorkingSet64/1MB), $proc.Handles, ((Get-Date) - $proc.StartTime).TotalHours
} else {
  $line = '{0},not-running,,,' -f (Get-Date -Format 'yyyy-MM-dd HH:mm:ss')
}
Add-Content -Path $log -Value $line -Encoding UTF8
Write-Output $line
