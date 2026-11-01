param([switch]$NoBrowser)
$ErrorActionPreference='Stop'
. F:\NeuroHead\use_f_storage.ps1
$root=Split-Path (Split-Path $PSScriptRoot -Parent) -Parent
$url='http://127.0.0.1:8766'
$existing=$null
try {$existing=Invoke-RestMethod "$url/health" -TimeoutSec 2} catch {}
if($existing -and $existing.service -ne 'nh_vision_dashboard'){throw '8766端口被其他程序占用；没有停止任何程序。'}
if(-not $existing){
 $app=Join-Path $PSScriptRoot 'server.py'
 Start-Process -FilePath 'F:\NeuroHead\environments\embodied_20261029\Scripts\pythonw.exe' -ArgumentList ('"'+$app+'"') -WorkingDirectory $root -WindowStyle Hidden -RedirectStandardOutput (Join-Path $root 'build\vision_dashboard_stdout.log') -RedirectStandardError (Join-Path $root 'build\vision_dashboard_stderr.log')
}
if(-not $NoBrowser){Start-Process $url}
