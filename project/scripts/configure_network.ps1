param([switch]$Restore)
$ErrorActionPreference = 'Stop'
$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$outDir = Join-Path $repoRoot 'build\network'
New-Item -ItemType Directory -Force -Path $outDir | Out-Null
$backupFile = Join-Path $outDir 'realtek_network_backup.json'
$adapter = @(Get-NetAdapter -Physical | Where-Object {$_.InterfaceDescription -eq 'Realtek PCIe GbE Family Controller'})
if ($adapter.Count -ne 1) { throw 'Expected exactly one dedicated Realtek physical adapter.' }
$idx = $adapter[0].ifIndex
if ($Restore) {
    if (-not (Test-Path -LiteralPath $backupFile)) { throw 'No saved configuration.' }
    $backup = Get-Content -Raw -LiteralPath $backupFile | ConvertFrom-Json
    if ($backup.mac -ne $adapter[0].MacAddress) { throw 'Adapter identity differs from backup.' }
    Get-NetIPAddress -InterfaceIndex $idx -AddressFamily IPv4 -IPAddress '192.168.10.10' -PolicyStore ActiveStore -ErrorAction SilentlyContinue |
        Remove-NetIPAddress -Confirm:$false
    Set-NetIPInterface -InterfaceIndex $idx -AddressFamily IPv4 -Dhcp $backup.dhcp -PolicyStore ActiveStore
    Write-Host 'Temporary board address removed; DHCP setting restored.'
    exit
}
$ips = @(Get-NetIPAddress -InterfaceIndex $idx -AddressFamily IPv4)
if (@($ips | Where-Object {$_.IPAddress -notlike '169.254.*' -and $_.IPAddress -ne '192.168.10.10'}).Count) {
    throw 'Adapter has a non-development address; refusing to replace it.'
}
if (-not (Test-Path -LiteralPath $backupFile)) {
    $ipif = Get-NetIPInterface -InterfaceIndex $idx -AddressFamily IPv4
    [ordered]@{name=$adapter[0].Name;mac=$adapter[0].MacAddress;dhcp=[string]$ipif.Dhcp;
        addresses=@($ips.IPAddress);saved_local=(Get-Date).ToString('o')} |
        ConvertTo-Json | Set-Content -LiteralPath $backupFile -Encoding UTF8
}
Set-NetIPInterface -InterfaceIndex $idx -AddressFamily IPv4 -Dhcp Disabled -PolicyStore ActiveStore
if (-not @($ips | Where-Object {$_.IPAddress -eq '192.168.10.10'}).Count) {
    New-NetIPAddress -InterfaceIndex $idx -AddressFamily IPv4 -IPAddress '192.168.10.10' -PrefixLength 24 -PolicyStore ActiveStore | Out-Null
}
$link = Get-NetAdapter -Name $adapter[0].Name
$assigned = @(Get-NetIPAddress -InterfaceIndex $idx -AddressFamily IPv4 | Where-Object {$_.IPAddress -eq '192.168.10.10'})
if ($assigned.Count -ne 1) { throw 'The requested IPv4 address was not found after configuration.' }
Write-Host "BOARD_IPV4: $($assigned[0].IPAddress)/$($assigned[0].PrefixLength) [$($assigned[0].AddressState)]"
Write-Host "ETHERNET_LINK: $($link.Status), $($link.LinkSpeed)"
Write-Host "BACKUP: $backupFile"
if ($link.Status -ne 'Up') {
    Write-Warning 'IPv4 is configured, but the physical Ethernet link is DOWN. Check cable/ports before UDP testing.'
} else {
    Write-Host 'IPv4 and physical link are ready for a read-only UDP probe; packet delivery is not yet verified.'
}
