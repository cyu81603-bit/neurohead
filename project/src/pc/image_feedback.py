"""Local image-feedback calibration and velocity integration; no device IO here."""
import math, statistics
LO,HI=1100,1900
def estimate_jacobian(samples):
    positions=[]
    for phase,target in enumerate((1500,1600,1500,1400,1500)):
        unique={s["source_frame"]:s for s in samples if s["phase"]==phase
                and s.get("settled_window",s["phase_elapsed_s"]>=.6) and s["output_us"]==target and s["face_x"] is not None}
        xs=[s["face_x"] for s in unique.values()]
        if len(xs)<5:raise ValueError("insufficient settled unique face frames")
        median=statistics.median(xs)
        if statistics.median(abs(x-median) for x in xs)>.04:
            raise ValueError("face not stationary enough for direction calibration")
        positions.append(median)
    c0,plus,c1,minus,c2=positions
    if max(c0,c1,c2)-min(c0,c1,c2)>.12:
        raise ValueError("neutral image position drifted; hold still for calibration")
    jp=(plus-(c0+c1)/2)/100
    jm=(minus-(c1+c2)/2)/-100
    if jp*jm<=0 or not .00015<=min(abs(jp),abs(jm))<=max(abs(jp),abs(jm))<=.02:
        raise ValueError("camera motion direction too weak or inconsistent")
    if max(abs(jp),abs(jm))/min(abs(jp),abs(jm))>3:
        raise ValueError("asymmetric image response; calibration not reliable")
    return {"image_dx_per_us":(jp+jm)/2,"positive_step_slope":jp,
            "negative_step_slope":jm,"settled_face_x":positions,
            "feedback_sign":-1 if jp>0 else 1}
class Feedback:
    def __init__(self,jacobian,gain=1.2,max_rate=350,lo=1100,hi=1900,neutral=1500):
        if not isinstance(jacobian,(int,float)) or not math.isfinite(jacobian) or not .00015<=abs(jacobian)<=.02:
            raise ValueError("invalid measured image Jacobian")
        if not 0<gain<=1.2 or not 0<max_rate<=350:raise ValueError("invalid controller gain or speed")
        if any(type(v) is not int for v in (lo,hi,neutral)) or not 600<=lo<=neutral<=hi<=2400:
            raise ValueError("invalid feedback pulse envelope")
        self.lo=lo;self.hi=hi;self.neutral=neutral
        self.gain=gain;self.max_rate=max_rate
        self.jacobian=jacobian;self.pulse=float(neutral);self.last_frame=None;self.last_time=None
        self.filtered=None;self.saturated=False
    def update(self,frame_id,frame_time,face_x):
        if self.last_frame==frame_id:return round(self.pulse)
        if self.last_frame is not None and frame_id<self.last_frame:
            raise ValueError("camera frame sequence reversed")
        if self.last_time is not None and frame_time<=self.last_time:
            raise ValueError("camera frame time reversed")
        dt=0 if self.last_time is None else min(.1,frame_time-self.last_time)
        self.last_frame=frame_id;self.last_time=frame_time
        if face_x is None:
            self.filtered=None
            return_rate=min(150,self.max_rate)
            self.pulse+=max(-return_rate*dt,min(return_rate*dt,self.neutral-self.pulse))
        else:
            if not math.isfinite(face_x) or not -1<=face_x<=1:raise ValueError("invalid face x")
            self.filtered=face_x if self.filtered is None else .5*face_x+.5*self.filtered
            rate=0 if abs(self.filtered)<.04 else max(-self.max_rate,min(self.max_rate,-self.gain*self.filtered/self.jacobian))
            desired=self.pulse+rate*dt
            self.pulse=max(self.lo,min(self.hi,desired))
            self.saturated=desired<self.lo or desired>self.hi
        return round(self.pulse)
