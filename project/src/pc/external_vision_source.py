"""Selected USB Cam preview with visible errors and bounded camera-only recovery."""
import argparse,json,sys,time
from pathlib import Path
from shared_hardware import SHARED_VISION_LOG,SHARED_VISION_STOP
from external_camera import NamedUvcCapture
from runtime_logs import JsonlLog
from vision_share import publish as publish_shared_frame
ROOT=Path(__file__).resolve().parents[2]
VENDORED_VISION=ROOT/"vendor/neurohead_vision/src/pc_vision"
sys.path.insert(0,str(VENDORED_VISION) if VENDORED_VISION.is_dir() else r"F:\NeuroHead\workspace\neurohead_fpga_2026\src\pc_vision")
from vision_source import VisionSource

class PreviewFeed:
    """Never publish an old image as a fresh detection after a capture failure."""
    def __init__(self,factory,clock=time.monotonic):
        self.factory=factory;self.clock=clock;self.source=None;self.attempts=0
        self.retry_at=0.;self.started=0.;self.last_frame_at=0.;self.last_id=0
        self.stable_since=None;self.error=None;self.closed=False;self.revision=0
    def retry(self):
        self.attempts=0;self.retry_at=self.clock();self.error=None;self.revision+=1
    def _failure(self,error,now):
        self.error=str(error);self.revision+=1
        if self.source:self.source.close()
        self.source=None;self.stable_since=None
        self.retry_at=now+min(8,2**max(0,self.attempts-1))
    def step(self):
        now=self.clock()
        if self.closed:return None,None,False
        if self.source is None and self.attempts<3 and now>=self.retry_at:
            self.attempts+=1;self.started=self.last_frame_at=now;self.last_id=0
            try:self.source=self.factory().start();self.error=None;self.revision+=1
            except Exception as exc:self._failure(exc,now)
        if self.source is None:return None,None,False
        packet,frame=self.source.snapshot()
        if packet.get('error'):
            self._failure(packet['error'],now);return None,None,False
        if packet.get('frame_id',0)>self.last_id:
            self.last_id=packet['frame_id'];self.last_frame_at=now
            if self.stable_since is None:self.stable_since=now
            if now-self.stable_since>=60:self.attempts=0
            return packet,frame,True
        if now-self.last_frame_at>(15 if not self.last_id else 3):
            self._failure('USB Cam未收到新画面',now)
        return None,None,False
    def status(self):
        if self.error:
            return 'USB Cam采集错误：'+self.error+('；请检查连接后点重试' if self.attempts>=3 else '；正在重连 %d/3'%self.attempts)
        return '正在打开 USB Cam；本窗口不发送舵机命令'
    def close(self):
        self.closed=True
        if self.source:self.source.close()
        self.source=None

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--duration',type=float,default=60);p.add_argument('--show',action='store_true')
    p.add_argument('--motion-telemetry',action='store_true');p.add_argument('--out',type=Path,default=SHARED_VISION_LOG);a=p.parse_args()
    if not 0<=a.duration<=3600:p.error('duration 0 means continuous; otherwise 0..3600 seconds')
    scene_motion=None
    if a.motion_telemetry:
        from scene_motion import SceneMotion
        scene_motion=SceneMotion()
    feed=PreviewFeed(lambda:VisionSource(camera_index='USB Cam',capture_factory=NamedUvcCapture))
    window=None;closed=[False];count=0;first=None;logged_revision=-1
    if a.show:
        import tkinter as tk
        from PIL import Image,ImageTk
        window=tk.Tk();window.title('NeuroHead 外接 USB Cam — 仅视觉预览')
        info=tk.StringVar(value=feed.status());tk.Label(window,textvariable=info,font=('Microsoft YaHei UI',12),wraplength=700).pack(padx=8,pady=8)
        picture=tk.Label(window);picture.pack()
        row=tk.Frame(window);row.pack(pady=8)
        tk.Button(row,text='重试USB Cam',command=feed.retry).pack(side='left',padx=8)
        tk.Button(row,text='关闭预览',command=lambda:closed.__setitem__(0,True)).pack(side='left',padx=8)
        window.protocol('WM_DELETE_WINDOW',lambda:closed.__setitem__(0,True));window.update()
    try:
        with JsonlLog(a.out) as log:
            while not closed[0]:
                now=time.monotonic();packet,frame,new=feed.step()
                if new:
                    if first is None:first=now
                    row=dict(mode='external_vision_preview',host_monotonic_s=now,vision=packet,robot_commands_sent=0,source_device='USB Cam',stream_duration_s=a.duration)
                    if scene_motion is not None and frame is not None:row['scene_motion']=scene_motion.update(frame,packet.get('box'),packet['frame_time'])
                    log.write_row(row);count+=1
                    publish_shared_frame(packet,frame)
                    if window is not None and frame is not None:
                        photo=ImageTk.PhotoImage(Image.fromarray(frame));picture.configure(image=photo,text='');picture.image=photo
                        info.set('USB Cam | 人脸 '+str(packet['face_count'])+' | 中心偏差 '+str(packet['target']))
                elif feed.error and logged_revision!=feed.revision:
                    log.write_row(dict(mode='external_vision_preview',host_monotonic_s=now,vision=dict(frame_id=0,frame_time=None,target=None,face_count=0,error=feed.error,running=False,camera_index='USB Cam'),robot_commands_sent=0,source_device='USB Cam'))
                if not new and (feed.error or feed.last_id==0) and window is not None:
                    info.set(feed.status());picture.configure(image='',text='暂无实时画面');picture.image=None
                logged_revision=feed.revision
                if window is not None:window.update()
                if SHARED_VISION_STOP.exists():break
                if a.duration>0 and now-(first if first is not None else feed.started)>=a.duration:break
                if window is None and feed.error and feed.attempts>=3:raise RuntimeError(feed.error)
                time.sleep(.01)
    finally:
        feed.close()
        if window is not None:window.destroy()
    print(json.dumps(dict(device='USB Cam',frames=count,jsonl=str(a.out),robot_commands_sent=0),indent=2))
if __name__=='__main__':main()
