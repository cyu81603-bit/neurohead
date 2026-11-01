$ErrorActionPreference='Stop'
. F:\NeuroHead\use_f_storage.ps1
$root=Split-Path $PSScriptRoot -Parent
Set-Location $root
$env:PYTHONPATH=$null
$env:PYTHONHOME=$null
$env:TCL_LIBRARY=$null
$env:TK_LIBRARY=$null
$env:QT_PLUGIN_PATH=$null
$env:PATH='F:\2026.1\Vivado\bin;C:\Windows\System32;C:\Windows;C:\Windows\System32\Wbem'
& 'F:\2026.1\Vivado\bin\vivado.bat' -mode batch -notrace -source scripts/driver.tcl -log build/vivado.log -journal build/vivado.jou
if($LASTEXITCODE -ne 0){throw 'Vivado build failed'}
