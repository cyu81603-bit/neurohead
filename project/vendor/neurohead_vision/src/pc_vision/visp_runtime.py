"""Launch the native ViSP runtime without changing the viewer's DLL environment."""
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PYTHON = ROOT / 'build/visp_env/python.exe'


def environment():
    env = os.environ.copy()
    prefix = PYTHON.parent
    system = Path(env.get('SystemRoot', r'C:\Windows'))
    env['PATH'] = os.pathsep.join(map(str, [prefix, prefix/'Library/bin', prefix/'DLLs',
                                          system/'System32', system]))
    for key in ('PYTHONHOME', 'PYTHONPATH', 'TCL_LIBRARY', 'TK_LIBRARY', 'QT_PLUGIN_PATH'):
        env.pop(key, None)
    env['OMP_NUM_THREADS'] = '1'
    env['MKL_NUM_THREADS'] = '1'
    env['PYTHONUNBUFFERED'] = '1'
    env['PYTHONNOUSERSITE'] = '1'
    storage = Path('F:/NeuroHead')
    env.update(TEMP=str(storage/'temp'), TMP=str(storage/'temp'),
               CONDA_PKGS_DIRS=str(storage/'cache/conda_pkgs'),
               PIP_CACHE_DIR=str(storage/'cache/pip'),
               MPLCONFIGDIR=str(storage/'cache/matplotlib'))
    return env
