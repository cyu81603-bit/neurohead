from shared_hardware import SHARED_VISION_LOG,SHARED_VISION_STOP
"""Five-axis heartbeat session with camera file IO off the control worker."""
import copy,threading,time
from neck_session import NeckSession
from head_control import HeadControl
from head_transport import HeadClient
from head_motion import LatestFrameBuffer
from vision_bridge import latest
from neck_yaw_midpoint import ROOT
class HeadSession(NeckSession):
    def __init__(self,profile,core_class=HeadControl,**kwargs):
        self._vision_mutex=threading.Lock();self._vision_row=None;self._vision_buffer=LatestFrameBuffer();self._vision_stop=threading.Event()
        kwargs.setdefault('period',.05)
        kwargs.setdefault('client_factory',HeadClient)
        super().__init__(profile,core_factory=lambda p,**k:core_class(p,vision=self.vision_snapshot,**k),**kwargs)
        self._reader=threading.Thread(target=self._vision_reader,name='head-vision-reader',daemon=True);self._reader.start()
    def vision_snapshot(self):
        with self._vision_mutex:return copy.deepcopy(self._vision_row)
    def _vision_reader(self):
        while not self._vision_stop.is_set():
            try:row=latest(SHARED_VISION_LOG)
            except (OSError,ValueError):row=None
            with self._vision_mutex:
                if self._vision_buffer.accept(row,now=time.monotonic()):self._vision_row=self._vision_buffer.row
            self._vision_stop.wait(.02)
    def set_targets(self,values):
        self._core.validate_targets(values)
        with self._mutex:self._pending_targets=list(values)
        self._wake.set()
    @property
    def extra(self):
        value=self._get('extra');value['target_tick_s']=self.period
        with self._vision_mutex:value.update(late_vision_frames=self._vision_buffer.late_frames,vision_read_errors=self._vision_buffer.read_errors)
        return value
    def set_follow(self,kind):return self._invoke('set_follow',kind)
    def set_motion_style(self,style):
        result=self._invoke('set_motion_style',style)
        self.period=.05
        profile=self.profile;profile['motion_style']=style;self.profile=profile
        return result
    def identify(self):return self._invoke('begin_identification')
    def close(self):
        if self.mode!='idle':raise RuntimeError('Support and end five-axis control first')
        self._vision_stop.set();super().close();self._reader.join(.5)