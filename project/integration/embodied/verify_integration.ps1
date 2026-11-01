param([switch]$LiveModels)
$ErrorActionPreference='Stop'
. F:\NeuroHead\use_f_storage.ps1
$env:PYTHONIOENCODING='utf-8'
$python='F:\NeuroHead\environments\embodied_20261029\Scripts\python.exe'
Push-Location $PSScriptRoot
try {
    & $python -m unittest test_integration -v
    if($LASTEXITCODE -ne 0){throw 'Integration tests failed'}
    & $python embodied_app.py --self-test
    if($LASTEXITCODE -ne 0){throw 'Idle UI test failed'}
    if($LiveModels){
        & $python check_local.py --llm
        if($LASTEXITCODE -ne 0){throw 'Local model test failed'}
    }
} finally {Pop-Location}
