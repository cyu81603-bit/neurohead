param([string]$Vivado='F:/2026.1/Vivado/bin/vivado.bat')
$ErrorActionPreference='Stop'
$root=Split-Path $PSScriptRoot -Parent
Set-Location $root
if(-not(Test-Path -LiteralPath $Vivado)){throw 'Set -Vivado'}
New-Item -ItemType Directory -Force -Path build|Out-Null
& $Vivado -mode batch -notrace -source scripts/driver.tcl -log build/vivado.log -journal build/vivado.jou
if($LASTEXITCODE -ne 0){throw 'Build failed'}
Write-Output 'Build only; no JTAG or actuator commands.'
