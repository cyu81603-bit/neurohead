"""Time-based gaze filtering and bounded continuous command trajectories. No IO."""
import math
from head_coordination import neck_pose,pitch_limit
from neck_presets import neck_neutral,rod_up_signs

def clamp(x,lo,hi):return max(lo,min(hi,x))
def blend(dt,tau):return 1-math.exp(-max(0,dt)/tau)
def validate_neck_rates(rates):
    if not isinstance(rates,(list,tuple)) or len(rates)!=2 or any(type(v) not in (int,float) or not math.isfinite(v) or not 0<v<=cap for v,cap in zip(rates,(50,35))):raise ValueError('Neck yaw/pitch rates must be finite, positive and <=50/35us/s')
    return list(rates)
class MotionAxis:
    def __init__(self,value,lo,hi):self.position=float(value);self.velocity=0.;self.acceleration=0.;self.lo=lo;self.hi=hi
    def reset(self,value):self.position=float(value);self.velocity=0.;self.acceleration=0.
    def step(self,target,dt,max_rate,max_accel,max_jerk):
        if not all(math.isfinite(v) for v in (target,dt,max_rate,max_accel,max_jerk)) or dt<0:raise ValueError('Invalid motion parameters')
        target=clamp(target,self.lo,self.hi);duration=min(dt,.1)
        if duration==0:return self.position
        steps=max(1,math.ceil(duration/.01));dt=duration/steps
        for _ in range(steps):
            error=target-self.position
            desired_velocity=clamp(6*error,-max_rate,max_rate)
            desired_accel=clamp((desired_velocity-self.velocity)/.04,-max_accel,max_accel)
            self.acceleration+=clamp(desired_accel-self.acceleration,-max_jerk*dt,max_jerk*dt)
            before=self.velocity;self.velocity=clamp(self.velocity+self.acceleration*dt,-max_rate,max_rate)
            self.position+=(before+self.velocity)*.5*dt
            if self.position<self.lo or self.position>self.hi:
                self.position=clamp(self.position,self.lo,self.hi);self.velocity=0.;self.acceleration=0.
            elif abs(target-self.position)<.12 and abs(self.velocity)<.6 and abs(self.acceleration)<4:
                self.position=target;self.velocity=0.;self.acceleration=0.
        return self.position
class MotionBank:
    def __init__(self,values,vertical_limits,reference=None,neck_rates=None):
        self.neck_rates=validate_neck_rates([20,15] if neck_rates is None else neck_rates)
        self.reference=list(reference or [1500,1270,1500])
        self.axes=[MotionAxis(value,lo,hi) for value,(lo,hi) in zip(values,[(1100,1900),tuple(vertical_limits)]+[(1100,1900)]*3)]
    def reset(self,values):
        for axis,value in zip(self.axes,values):axis.reset(value)
    def step(self,targets,dt,coordinated=False):
        for k,axis in enumerate(self.axes[2:]):
            axis.lo,axis.hi=(self.reference[k]-100,self.reference[k]+100) if coordinated else (1100,1900)
        yaw,pitch=self.neck_rates
        rates=[200,100,yaw if coordinated else 100,pitch if coordinated else 100,pitch if coordinated else 100]
        accels=[700,450,yaw*3.25 if coordinated else 200,pitch*10/3 if coordinated else 200,pitch*10/3 if coordinated else 200]
        jerks=[5000,3500,yaw*25 if coordinated else 1400,pitch*80/3 if coordinated else 1400,pitch*80/3 if coordinated else 1400]
        return [axis.step(value,dt,rate,accel,jerk) for axis,value,rate,accel,jerk in zip(self.axes,targets,rates,accels,jerks)]

class NaturalEye:
    def __init__(self,jacobian,max_rate,lo,hi):
        self.jacobian=jacobian;self.max_rate=max_rate;self.lo=lo;self.hi=hi
        self.pulse=1500.;self.filtered=None;self.velocity=0.;self.fixating=False;self.missing_age=0.
    def update(self,error,dt,actual):
        if error is None:
            self.missing_age+=dt;self.filtered=None;self.velocity=0.
            if self.missing_age<=.4:return round(self.pulse)
            self.pulse+=clamp(1500-self.pulse,-60*dt,60*dt)
        else:
            self.missing_age=0.
            self.filtered=error if self.filtered is None else self.filtered+blend(dt,.08)*(error-self.filtered)
            if self.fixating:
                if abs(self.filtered)>.055:self.fixating=False
            elif abs(self.filtered)<.025:self.fixating=True
            rate=0 if self.fixating else clamp(-.8*self.filtered/self.jacobian,-self.max_rate,self.max_rate)
            self.velocity+=blend(dt,.06)*(rate-self.velocity)
            self.pulse+=self.velocity*dt
            # Tracking anti-windup: the target cannot run far ahead of command output.
            lead=35 if self.max_rate>100 else 25
            self.pulse=clamp(self.pulse,actual-lead,actual+lead)
        self.pulse=clamp(self.pulse,self.lo,self.hi)
        return round(self.pulse)
class NaturalCoordinator:
    def __init__(self,profile,values):
        self.profile=profile;self.reference=neck_neutral(profile);self.last_frame=None;self.last_time=None
        vlo,vhi=profile.get('eye_vertical_limits_us',[1000,2000])
        self.eye=[NaturalEye(.002,200,1100,1900),NaturalEye(-.002 if profile.get('vertical_reverse') else .002,100,vlo,vhi)]
        for eye,value in zip(self.eye,values):eye.pulse=float(value)
        self.yaw=float(values[2]-self.reference[0]);signs=rod_up_signs(profile)
        self.pitch=sum((values[k+3]-self.reference[k+1])*signs[k] for k in (0,1))/2
        self.offsets=[0.,0.];self.neck_rates=[0.,0.];self.active_age=0.
    def update(self,v,values,calibration=None):
        frame=v['frame_id'];stamp=v['frame_time'];target=v['target']
        if self.last_frame is not None and (frame<=self.last_frame or stamp<=self.last_time):return None
        dt=0 if self.last_time is None else min(.1,stamp-self.last_time)
        self.last_frame=frame;self.last_time=stamp
        eyes=[eye.update(None if target is None else target[k],dt,values[k]) for k,eye in enumerate(self.eye)]
        self.active_age=self.active_age+dt if target is not None else 0.
        if calibration is None:return eyes+list(values[2:])
        if not calibration.get('valid') or calibration.get('reference_us')!=self.reference:raise ValueError('Neck reference mismatch')
        raw=[0.,0.]
        if target is not None:
            for k in (0,1):self.offsets[k]+=blend(dt,.28)*(values[k]-1500-self.offsets[k])
            engage=clamp((self.active_age-.15)/.45,0,1);engage=engage*engage*(3-2*engage)
            image=[self.eye[k].jacobian*(offset-50*math.tanh(offset/50))*.35*engage for k,offset in enumerate(self.offsets)]
            raw=[sum(a*b for a,b in zip(row,image)) for row in calibration['inverse']]
        caps=[min(20,calibration.get('automatic_yaw_rate_us_per_s',20)),min(15,calibration.get('automatic_pitch_rate_us_per_s',15))]
        limits=[min(100,calibration.get('automatic_yaw_limit_us',100)),min(pitch_limit(self.profile),100,calibration.get('automatic_pitch_limit_us',100))]
        positions=[self.yaw,self.pitch]
        for k in (0,1):
            wanted=clamp(raw[k],-caps[k],caps[k]);remaining=limits[k]-(positions[k] if wanted>0 else -positions[k]) if wanted else limits[k]
            # Ease into the software envelope instead of hitting it at constant speed.
            wanted*=clamp(remaining/15,0,1)
            self.neck_rates[k]+=blend(dt,.25)*(wanted-self.neck_rates[k])
            if target is None:self.neck_rates[k]=0.
            positions[k]=clamp(positions[k]+self.neck_rates[k]*dt,-limits[k],limits[k])
        self.yaw,self.pitch=positions
        return eyes+neck_pose(self.profile,self.yaw,self.pitch)

class LatestFrameBuffer:
    """Ignore late file snapshots while retaining the last fresh camera frame."""
    def __init__(self):self.row=None;self.late_frames=0;self.read_errors=0
    def accept(self,row,now=None):
        if not isinstance(row,dict) or not isinstance(row.get('vision'),dict):self.read_errors+=1;return False
        v=row['vision'];stamp=v.get('frame_time');frame=v.get('frame_id')
        if type(stamp) not in (int,float) or not math.isfinite(stamp) or type(frame) is not int:return False
        def fresh(candidate):
            stamps=(candidate.get('host_monotonic_s'),candidate['vision'].get('frame_time'))
            return all(type(t) in (int,float) and math.isfinite(t) and 0<=now-t<=.75 for t in stamps)
        # Monotonic timestamps from a previous Windows boot are not comparable.
        # Reject them before establishing the high-water mark for this process.
        if now is not None and not fresh(row):self.late_frames+=1;return False
        if self.row is not None:
            old=self.row['vision'];same=v.get('source_session_id')==old.get('source_session_id')
            if now is not None and not same and not fresh(self.row):
                self.row=row;return True
            if same and frame==old['frame_id'] and stamp==old['frame_time']:return False
            if stamp<=old['frame_time'] or (same and frame<=old['frame_id']):self.late_frames+=1;return False
        self.row=row;return True