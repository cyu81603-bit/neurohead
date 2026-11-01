# Dot-source this script before terminal builds/downloads:
# . F:\NeuroHead\use_f_storage.ps1
$env:NEUROHEAD_STORAGE_ROOT = 'F:\NeuroHead'
$env:CONDA_PKGS_DIRS = 'F:\NeuroHead\cache\conda_pkgs'
$env:CONDA_ENVS_PATH = 'F:\NeuroHead\environments'
$env:PIP_CACHE_DIR = 'F:\NeuroHead\cache\pip'
$env:MPLCONFIGDIR = 'F:\NeuroHead\cache\matplotlib'
$env:PYTHONNOUSERSITE = '1'
$env:TEMP = 'F:\NeuroHead\temp'
$env:TMP = 'F:\NeuroHead\temp'
foreach ($neuroheadStorageDirectory in @($env:CONDA_PKGS_DIRS,$env:CONDA_ENVS_PATH,
    $env:PIP_CACHE_DIR,$env:MPLCONFIGDIR,$env:TEMP)) {
    New-Item -ItemType Directory -Path $neuroheadStorageDirectory -Force | Out-Null
}
