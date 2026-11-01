$ErrorActionPreference='Stop'
. F:\NeuroHead\use_f_storage.ps1
$root=Split-Path (Split-Path $PSScriptRoot -Parent) -Parent
$statusPath=Join-Path $PSScriptRoot 'build\teammate_ui_audio2_status.json'
if(Test-Path -LiteralPath $statusPath){
 try {
  $s=Get-Content -LiteralPath $statusPath -Raw -Encoding UTF8|ConvertFrom-Json
  if(([DateTimeOffset]::UtcNow.ToUnixTimeSeconds()-$s.updated) -lt 5 -and (Get-Process -Id $s.pid -ErrorAction SilentlyContinue)){return}
 } catch {}
}
$app=Join-Path $PSScriptRoot 'teammate_panel.py'
Start-Process -FilePath 'F:\NeuroHead\environments\embodied_20261029\Scripts\pythonw.exe' -ArgumentList ('"'+$app+'"') -WorkingDirectory $root -WindowStyle Hidden -RedirectStandardOutput (Join-Path $root 'build\teammate_ui_stdout.log') -RedirectStandardError (Join-Path $root 'build\teammate_ui_stderr.log')
