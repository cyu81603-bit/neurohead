"""Accumulate fine pitch targets into explicit, rate-limited servo commands.
A development hypothesis about useful command size, not a measured servo deadband.
"""
import math
class EffectivePulseOutput:
    def __init__(self,lo,hi,neutral=1500,quantum_us=10,max_rate_us_per_s=100):
        if any(type(v) is not int for v in (lo,hi,neutral,quantum_us)) or not lo<=neutral<=hi:
            raise ValueError("invalid output envelope")
        if quantum_us not in (1,2,5,10) or (neutral-lo)%quantum_us or (hi-neutral)%quantum_us:
            raise ValueError("pulse quantum must divide both half-spans")
        if not 0<max_rate_us_per_s<=100:raise ValueError("invalid pitch command rate")
        self.lo=lo;self.hi=hi;self.command=neutral;self.quantum=quantum_us
        self.max_rate=max_rate_us_per_s;self.last_frame=None;self.last_time=None;self.last_emit=None
    def update(self,desired,frame_id,frame_time):
        if not isinstance(desired,(int,float)) or not math.isfinite(desired) or not self.lo<=desired<=self.hi:
            raise ValueError("desired pulse outside output envelope")
        if not isinstance(frame_time,(int,float)) or not math.isfinite(frame_time):raise ValueError("invalid frame time")
        if frame_id==self.last_frame:return self.command
        if self.last_time is not None and frame_time<=self.last_time:raise ValueError("frame time reversed")
        if self.last_frame is not None and frame_id<self.last_frame:raise ValueError("frame sequence reversed")
        self.last_frame=frame_id;self.last_time=frame_time
        if self.last_emit is None:self.last_emit=frame_time
        difference=desired-self.command
        if abs(difference)>=self.quantum and frame_time-self.last_emit+1e-9>=self.quantum/self.max_rate:
            self.command+=self.quantum if difference>0 else -self.quantum
            self.last_emit=frame_time
        return self.command
