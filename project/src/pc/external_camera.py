"""Named external UVC capture for the original VisionSource API.
Uses the explicitly selected DirectShow name USB Cam. No fallback to camera index zero.
"""
import json,queue,subprocess,threading
from pathlib import Path

class NamedUvcCapture:
    def __init__(self,config_path=None):
        import numpy as np
        self.np=np
        root=Path(__file__).resolve().parents[2]
        self.config=json.loads(Path(config_path or root/"config/camera.json").read_text(encoding="utf-8-sig"))
        self.width=self.config["width"];self.height=self.config["height"]
        self.frames=queue.Queue(maxsize=1);self.closed=False
        self.log=(root/"build/external_camera_ffmpeg.log").open("wb")
        command=[self.config["ffmpeg"],"-hide_banner","-loglevel","error","-f","dshow",
                 "-video_size",str(self.width)+"x"+str(self.height),"-framerate",str(self.config["fps"]),
                 "-vcodec","mjpeg","-i","video="+self.config["device_name"],"-an","-threads","1","-pix_fmt","bgr24","-f","rawvideo","pipe:1"]
        self.process=subprocess.Popen(command,stdout=subprocess.PIPE,stderr=self.log,
                                      creationflags=getattr(subprocess,"CREATE_NO_WINDOW",0))
        self.thread=threading.Thread(target=self._pump,daemon=True)
        self.thread.start()
    def _pump(self):
        size=self.width*self.height*3
        while not self.closed:
            data=bytearray()
            while len(data)<size and not self.closed:
                block=self.process.stdout.read(size-len(data))
                if not block:return
                data.extend(block)
            if len(data)!=size:return
            frame=self.np.frombuffer(data,dtype=self.np.uint8).reshape(self.height,self.width,3).copy()
            try:self.frames.get_nowait()
            except queue.Empty:pass
            self.frames.put_nowait(frame)
    def isOpened(self):
        return not self.closed and self.process.poll() is None
    def set(self,prop,value):
        return True
    def read(self):
        try:return True,self.frames.get(timeout=10)
        except queue.Empty:return False,None
    def release(self):
        if self.closed:return
        self.closed=True
        if self.process.poll() is None:
            self.process.terminate()
            try:self.process.wait(timeout=2)
            except subprocess.TimeoutExpired:self.process.kill();self.process.wait(timeout=2)
        self.process.stdout.close();self.thread.join(timeout=1);self.log.close()
