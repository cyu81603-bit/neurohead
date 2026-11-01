"""Optional intent link to the existing controller; never a UDP owner."""
import json
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

ROOT=Path(__file__).resolve().parents[2]


class RemoteSession:
    def state(self):
        states=[]
        for p in (ROOT/'build').glob('head_runtime_*.json'):
            try:s=json.loads(p.read_text(encoding='utf-8'))
            except (OSError,ValueError):continue
            if 0<=time.time()-s.get('updated_epoch',0)<4 and s.get('mode')=='running':states.append(s)
        return max(states,key=lambda s:s['updated_epoch']) if states else {}
    @property
    def mode(self):return self.state().get('mode','idle')
    @property
    def extra(self):return self.state()
    def life_event(self,event):
        cfg=json.loads((ROOT/'build/lifelike_api.json').read_text(encoding='utf-8'))
        if cfg.get('pid')!=self.state().get('owner_pid'):raise ValueError('请在正在控制的窗口启动本机LLM/TTS接口')
        if cfg['url']!='http://127.0.0.1:8765':raise ValueError('只允许本机表情接口')
        req=urllib.request.Request(cfg['url']+'/events',data=json.dumps(event).encode('utf-8'),
            headers={'Content-Type':'application/json','X-NeuroHead-Key':cfg['key']},method='POST')
        with urllib.request.urlopen(req,timeout=.5) as r:return json.load(r)


class RemoteController:
    def __init__(self):self.control=RemoteSession()
    def open_camera(self):
        from vision_share import read
        try:read();return
        except (OSError,ValueError,KeyError):pass
        # A fresh tracking log may belong to an older preview; do not open a second camera.
        from shared_hardware import SHARED_VISION_LOG
        from vision_bridge import latest
        try:
            if 0<=time.monotonic()-latest(SHARED_VISION_LOG)['host_monotonic_s']<.75:return
        except (OSError,ValueError,KeyError):pass
        with (ROOT/'build/dialogue_camera.log').open('ab') as log:
            subprocess.Popen([sys.executable,str(ROOT/'src/pc/external_vision_source.py'),'--show','--duration','0'],
                cwd=ROOT,stdout=log,stderr=log,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
