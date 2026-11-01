"""Capture a startup image reference at servo neutral; not camera calibration."""
import math,statistics
class StartupVerticalReference:
    def __init__(self,settle_s=.8,required_frames=5):
        self.settle_s=settle_s;self.required_frames=required_frames
        self.started=None;self.last_frame=None;self.samples=[];self.value=None
    def observe(self,frame_id,frame_time,y):
        if self.value is not None:return self.value
        if self.started is None:self.started=frame_time
        if self.last_frame==frame_id:return None
        self.last_frame=frame_id
        if frame_time-self.started<self.settle_s or y is None:return None
        if not isinstance(y,(int,float)) or not math.isfinite(y) or not -1<=y<=1:
            raise ValueError("invalid startup vertical reference")
        self.samples.append(y)
        if len(self.samples)>=self.required_frames:self.value=statistics.median(self.samples[-self.required_frames:])
        return self.value
