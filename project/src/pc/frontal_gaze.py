"""Head-centric image feedback inside the existing verified neck envelope."""
import math
from head_motion import NaturalCoordinator,blend,clamp,validate_neck_rates
from head_coordination import neck_pose,pitch_limit
class FrontalCoordinator(NaturalCoordinator):
    def __init__(self,profile,values):
        super().__init__(profile,values);self.scene_error=[0.,0.]
        requested=profile.get('neck_tracking_rate_us_per_s')
        self.rate_caps=None if requested is None else validate_neck_rates(requested)
        self.gain=profile.get('neck_tracking_gain',.35)
        self.set_headroom(profile.get('head_up_reserve_us',0))
        if type(self.gain) not in (int,float) or not math.isfinite(self.gain) or not .1<=self.gain<=.8:raise ValueError('Invalid neck tracking gain')
        defaults=dict(engage_delay_s=.15,engage_ramp_s=.45,eye_offset_tau_s=.18,image_error_tau_s=.12,neck_rate_tau_s=.25)
        overrides=profile.get('frontal_response',{})
        if not isinstance(overrides,dict) or set(overrides)-set(defaults):raise ValueError('Invalid frontal response settings')
        self.response=dict(defaults,**overrides)
        for name,value in self.response.items():
            lo=0 if name=='engage_delay_s' else .05
            if type(value) not in (int,float) or not math.isfinite(value) or not lo<=value<=1:raise ValueError('Invalid frontal response timing: '+name)
    def set_headroom(self,reserve):
        if type(reserve) is not int or not 0<=reserve<=100:raise ValueError('Invalid head-up tracking reserve')
        self.head_up_reserve_us=reserve
    def update(self,v,values,calibration=None):
        frame=v['frame_id'];stamp=v['frame_time'];target=v['target']
        if self.last_frame is not None and (frame<=self.last_frame or stamp<=self.last_time):return None
        dt=0 if self.last_time is None else min(.1,stamp-self.last_time);self.last_frame=frame;self.last_time=stamp
        eyes=[eye.update(None if target is None else target[k],dt,values[k]) for k,eye in enumerate(self.eye)]
        self.active_age=self.active_age+dt if target is not None else 0.
        if calibration is None:return eyes+list(values[2:])
        if not calibration.get('valid') or calibration.get('reference_us')!=self.reference:raise ValueError('Neck reference mismatch')
        wanted=[0.,0.]
        if target is not None:
            for k in (0,1):
                self.offsets[k]+=blend(dt,self.response['eye_offset_tau_s'])*(values[k]-1500-self.offsets[k]);self.scene_error[k]+=blend(dt,self.response['image_error_tau_s'])*(target[k]-self.scene_error[k])
            engage=clamp((self.active_age-self.response['engage_delay_s'])/self.response['engage_ramp_s'],0,1);engage=engage*engage*(3-2*engage)
            image=[(self.eye[k].jacobian*(o-20*math.tanh(o/20))-(e-.025*math.tanh(e/.025)))*self.gain*engage for k,(o,e) in enumerate(zip(self.offsets,self.scene_error))]
            wanted=[sum(a*b for a,b in zip(row,image)) for row in calibration['inverse']]
        limits=[min(100,calibration.get('automatic_yaw_limit_us',100)),min(pitch_limit(self.profile),100,calibration.get('automatic_pitch_limit_us',100))]
        caps=self.rate_caps if self.rate_caps is not None else [min(20,calibration.get('automatic_yaw_rate_us_per_s',20)),min(15,calibration.get('automatic_pitch_rate_us_per_s',15))];positions=[self.yaw,self.pitch]
        for k in (0,1):
            upper=limits[k] if k==0 else max(-limits[k],limits[k]-self.head_up_reserve_us)
            if k==1 and positions[k]>upper:
                if target is None:self.neck_rates[k]=0.;continue
                # Retire an old saturated tracking pose at the tracking rate.
                # Do not snap the internal target or lower as an action prelude.
                self.neck_rates[k]=min(0.,self.neck_rates[k])
                self.neck_rates[k]+=blend(dt,self.response['neck_rate_tau_s'])*(-caps[k]-self.neck_rates[k])
                positions[k]=max(upper,positions[k]+self.neck_rates[k]*dt)
                continue
            rate=clamp(wanted[k],-caps[k],caps[k]);remaining=upper-positions[k] if rate>0 else limits[k]+positions[k]
            rate*=clamp(remaining/15,0,1);self.neck_rates[k]+=blend(dt,self.response['neck_rate_tau_s'])*(rate-self.neck_rates[k])
            if target is None:self.neck_rates[k]=0.
            positions[k]=clamp(positions[k]+self.neck_rates[k]*dt,-limits[k],upper)
        self.yaw,self.pitch=positions;return eyes+neck_pose(self.profile,self.yaw,self.pitch)
