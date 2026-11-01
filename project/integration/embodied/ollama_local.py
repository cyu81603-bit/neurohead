"""Reuse the existing local service, or start only the user's F-drive install."""
import json
import os
import subprocess
import time
import urllib.request
import config


def ensure_service():
    def probe():
        with urllib.request.urlopen('http://127.0.0.1:11434/api/tags',timeout=2) as r:
            return json.load(r)
    try: return probe()
    except OSError:
        if not config.OLLAMA_EXE.is_file():raise RuntimeError('未找到F盘Ollama安装')
        env=dict(os.environ,OLLAMA_MODELS=str(config.OLLAMA_MODELS_DIR),OLLAMA_HOST='127.0.0.1:11434')
        subprocess.Popen([str(config.OLLAMA_EXE),'serve'],env=env,
            stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,
            creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        for _ in range(16):
            time.sleep(.5)
            try:return probe()
            except OSError:pass
        raise RuntimeError('F盘Ollama服务未能启动')
