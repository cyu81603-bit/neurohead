$ErrorActionPreference='Stop'
. F:\NeuroHead\use_f_storage.ps1
$root=Split-Path (Split-Path $PSScriptRoot -Parent) -Parent
$python='F:\NeuroHead\environments\embodied_20261029\Scripts\pythonw.exe'
$app=Join-Path $root 'integration\embodied\embodied_app.py'
try { $null=Invoke-RestMethod -Uri 'http://127.0.0.1:11434/api/tags' -TimeoutSec 3 }
catch {
    $env:OLLAMA_MODELS='F:\Ollama\models'
    $env:OLLAMA_HOST='127.0.0.1:11434'
    Start-Process -FilePath 'F:\Ollama\ollama.exe' -ArgumentList 'serve' -WindowStyle Hidden
}
$existing=Get-ChildItem -LiteralPath (Join-Path $root 'build') -Filter 'head_runtime_*.json' |
    ForEach-Object { try { Get-Content -LiteralPath $_.FullName -Raw | ConvertFrom-Json } catch {} } |
    Where-Object { $_.integration_revision -eq 63 -and $_.frontal_response_revision -eq 1 -and $_.left_lower_lid_guard_revision -eq 1 -and $_.expression_presets_revision -eq 1 -and $_.action_library_revision -eq 1 -and $_.action_execution_revision -eq 6 -and $_.semantic_policy_revision -eq 2 -and $_.right_wink_revision -eq 1 -and $_.camera_lid_guard_revision -eq 1 -and ([DateTimeOffset]::UtcNow.ToUnixTimeSeconds()-$_.updated_epoch) -lt 4 -and (Get-Process -Id $_.owner_pid -ErrorAction SilentlyContinue) }
if ($existing) { & (Join-Path $PSScriptRoot 'start_teammate.ps1'); return }
$other=Get-ChildItem -LiteralPath (Join-Path $root 'build') -Filter 'head_runtime_*.json' |
    ForEach-Object {try {Get-Content -LiteralPath $_.FullName -Raw|ConvertFrom-Json}catch{}} |
    Where-Object {([DateTimeOffset]::UtcNow.ToUnixTimeSeconds()-$_.updated_epoch) -lt 4 -and (Get-Process -Id $_.owner_pid -ErrorAction SilentlyContinue)}
if($other){Write-Output '现有旧版主控仍在运行。请托稳并结束旧会话、关闭旧主控后再启动R5；本次未创建第二个控制器。';return}
Start-Process -FilePath $python -ArgumentList ('"'+$app+'"') -WorkingDirectory $root -WindowStyle Hidden `
    -RedirectStandardOutput (Join-Path $root 'build\embodied_v6_3_stdout.log') `
    -RedirectStandardError (Join-Path $root 'build\embodied_v6_3_stderr.log')
