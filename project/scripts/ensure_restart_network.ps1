param([switch]$Worker,[switch]$CheckOnly)
$ErrorActionPreference='Stop'
[Console]::OutputEncoding=[Text.UTF8Encoding]::new($false)
$root=Split-Path $PSScriptRoot -Parent
if($Worker){
    & (Join-Path $PSScriptRoot 'configure_network.ps1')
    exit 0
}
$adapters=@(Get-NetAdapter -Physical | Where-Object {$_.InterfaceDescription -eq 'Realtek PCIe GbE Family Controller'})
if($adapters.Count -ne 1){throw 'Expected exactly one dedicated Realtek board adapter.'}
$adapter=$adapters[0];$idx=$adapter.ifIndex
if($adapter.Status -ne 'Up'){throw 'Dedicated Ethernet link is down. Check board power and cable.'}
$ips=@(Get-NetIPAddress -InterfaceIndex $idx -AddressFamily IPv4 -ErrorAction Stop)
if(@($ips | Where-Object {$_.IPAddress -notlike '169.254.*' -and $_.IPAddress -ne '192.168.10.10'}).Count){throw 'Dedicated adapter has another address; refusing to replace it.'}
$assigned=@($ips | Where-Object {$_.IPAddress -eq '192.168.10.10'})
if($assigned.Count -and $assigned[0].PrefixLength -ne 24){throw 'Existing board IPv4 has a different prefix; inspect manually.'}
if(-not $assigned.Count){
    if($CheckOnly){Write-Output 'NETWORK_CONFIGURATION_REQUIRED';exit 2}
    Write-Output 'NETWORK_ADMIN_PERMISSION_REQUESTED'
    $admin=Start-Process -FilePath powershell.exe -Verb RunAs -WindowStyle Hidden -ArgumentList @('-NoProfile','-ExecutionPolicy','Bypass','-File',(Join-Path $PSScriptRoot 'ensure_restart_network.ps1'),'-Worker') -PassThru
    if(-not $admin.WaitForExit(45000)){throw 'Network helper still waiting; recovery has not loaded the board.'}
    if($admin.ExitCode -ne 0){throw 'Administrator network helper failed or was cancelled.'}
}
$preferred=@()
for($attempt=0;$attempt -lt 15;$attempt++){
    $preferred=@(Get-NetIPAddress -InterfaceIndex $idx -AddressFamily IPv4 -ErrorAction Stop | Where-Object {$_.IPAddress -eq '192.168.10.10' -and $_.PrefixLength -eq 24 -and $_.AddressState -eq 'Preferred'})
    if($preferred.Count -eq 1){break}
    Start-Sleep -Milliseconds 200
}
if($preferred.Count -ne 1){throw 'Board address is not ready after configuration.'}
Write-Output ('NETWORK_READY: 192.168.10.10/24 on '+$adapter.Name)
