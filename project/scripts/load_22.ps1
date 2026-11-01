param([switch]$ServoPowerOff,[switch]$SignalsDisconnected,[switch]$RecoveryAssetsOnly,[switch]$ValidateOnly)
$ErrorActionPreference='Stop'
. F:\NeuroHead\use_f_storage.ps1
$root=Split-Path $PSScriptRoot -Parent
Set-Location $root
$manifest=Get-Content -LiteralPath "$root\build\release_manifest.json" -Raw | ConvertFrom-Json -AsHashtable
if($manifest.status -notin @('offline_pass_not_board_validated','development_build_pass')){throw 'No passing development manifest'}
$recoveryAssets=@{
 'build\firmware\nh22_udp.bin'='3c77efab811dcc82bbd660123b3a5be7f8f0053882a9e0a068c8186832e76e6f'
 'build\reports\zynq_neurohead\neurohead_zynq.bit'='535d2a37ab01f9ffa5b005ba8ce62ae4eac23fcf341d2a404a89460d09c91fbb'
 'build\reports\zynq_neurohead\ps7_init.tcl'='16895e9ca2d108224318b3cbf5453c77fdeb0e4c22fb01c2e1b745d3c4200f77'
 'scripts\load_monitor_jtag.tcl'='b50febf525c6830dfa57485c27e88b14fc782670abf82ec3ca2da49127a85452'
}
# Runtime calibration/config/UI files legitimately change after each session.
# Recovery still pins all four files executed or programmed by JTAG.
$filesToCheck=if($RecoveryAssetsOnly){$recoveryAssets}else{$manifest.files}
foreach($entry in $filesToCheck.GetEnumerator()){
 if($RecoveryAssetsOnly -and $manifest.files[$entry.Key] -ne $entry.Value){throw 'Recovery asset manifest differs from accepted image'}

 $path=Join-Path $root $entry.Key
 if((Get-FileHash -LiteralPath $path -Algorithm SHA256).Hash.ToLower() -ne $entry.Value){throw "Artifact hash mismatch: $path"}
}
if($ValidateOnly){Write-Output 'PROGRAM_ASSETS_VERIFIED_NO_JTAG';return}
if(-not $ServoPowerOff -or -not $SignalsDisconnected){
 throw 'Before JTAG: confirm external servo supply OFF and all PWM signal wires disconnected; then pass -ServoPowerOff -SignalsDisconnected.'
}
$launchTranscript = & 'F:\2026.1\Vitis\bin\xsdb.bat' "$root\scripts\load_monitor_jtag.tcl" "$root\build\reports\zynq_neurohead\ps7_init.tcl" "$root\build\firmware\nh22_udp.bin" "$root\build\reports\zynq_neurohead\neurohead_zynq.bit" 2>&1
$launchExit = $LASTEXITCODE
$launchTranscript | ForEach-Object { Write-Output $_ }
if($launchExit -ne 0 -or -not ($launchTranscript -match '^MONITOR_BINARY_JTAG_LAUNCHED:')){
 throw 'JTAG load did not report a successful firmware launch; do not reconnect servos.'
}
Write-Output 'Loaded development image. Run query only before connecting a servo.'
