$ErrorActionPreference='Stop'
$root=Split-Path $PSScriptRoot -Parent
function Install-Missing($source,$dest){
 if(Test-Path -LiteralPath $dest){
  if((Get-FileHash -LiteralPath $source).Hash -ne (Get-FileHash -LiteralPath $dest).Hash){throw "Existing file differs, left untouched: $dest"}
 }else{New-Item -ItemType Directory -Force -Path (Split-Path $dest -Parent)|Out-Null;Copy-Item -LiteralPath $source -Destination $dest}
}
Install-Missing (Join-Path $root 'support/use_f_storage.ps1') 'F:/NeuroHead/use_f_storage.ps1'
Install-Missing (Join-Path $root 'support/original_eye_horizontal.json') 'F:/NeuroHead/workspace/neurohead_fpga_2026/data/joint_setups/eye_horizontal.json'
New-Item -ItemType Directory -Force -Path 'F:/NeuroHead/builds/nh21_20261024/build'|Out-Null
Write-Output 'Support files only. No controller started; no board programming.'
