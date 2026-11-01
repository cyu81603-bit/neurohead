param([string]$Python='F:/NeuroHead/environments/embodied_20261029/Scripts/python.exe')
$ErrorActionPreference='Stop'
$root=Split-Path $PSScriptRoot -Parent
if(-not(Test-Path -LiteralPath $Python)){throw 'Set -Python to installed venv python.exe'}
$active=Get-ChildItem 'F:/NeuroHead/builds/*/build/head_runtime_*.json' -ErrorAction SilentlyContinue | ForEach-Object {try {Get-Content -LiteralPath $_.FullName -Raw|ConvertFrom-Json}catch{}} | Where-Object {([DateTimeOffset]::UtcNow.ToUnixTimeSeconds()-$_.updated_epoch)-lt 4 -and (Get-Process -Id $_.owner_pid -ErrorAction SilentlyContinue)}
if($active){throw 'Existing controller is alive; support the head and stop it through its own panel first.'}
& $Python (Join-Path $root 'integration/embodied/embodied_app.py')
