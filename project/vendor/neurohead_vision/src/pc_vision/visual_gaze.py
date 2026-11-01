"""Virtual gaze coordination only. No pulse conversion, sockets or actuator IO."""
import math


def clamp(value,low,high):return max(low,min(high,value))


class VisualGaze:
    """Illustrative fixed-camera mapping; not calibrated robot kinematics."""
    def __init__(self):
        self.pose=dict(neck_pan=0.,neck_tilt=0.,neck_roll=0.,eye_pan=0.,eye_tilt=0.,jaw_open=0.)
        self.last_time=None
        self.last_seen=None
        self.desired=(0.,0.)
        self.status='waiting'

    def step(self,target,frame_time,now):
        dt=0.05 if self.last_time is None else clamp(now-self.last_time,0,.3)
        self.last_time=now
        fresh=isinstance(frame_time,(int,float)) and math.isfinite(frame_time) and 0<=now-frame_time<=.5
        valid=(fresh and isinstance(target,(list,tuple)) and len(target)==2 and
               all(isinstance(x,(int,float)) and math.isfinite(x) for x in target))
        if valid:
            nx,ny=(clamp(x,-1,1) for x in target)
            nx=0. if abs(nx)<.04 else nx
            ny=0. if abs(ny)<.04 else ny
            self.desired=(nx*28,ny*16)
            self.last_seen=frame_time
            self.status='tracking'
        elif self.last_seen is not None and 0<=now-self.last_seen<=.6:
            self.status='brief_target_loss'
        else:
            self.desired=(0.,0.)
            self.status='no_target' if fresh else 'camera_stale'
        yaw,pitch=self.desired
        neck_yaw=math.copysign(max(0,abs(yaw)-10),yaw)
        neck_pitch=math.copysign(max(0,abs(pitch)-5),pitch)
        head_alpha=-math.expm1(-dt/.65)
        eye_alpha=-math.expm1(-dt/.10)
        for key,goal in (('neck_pan',clamp(neck_yaw,-18,18)),('neck_tilt',clamp(neck_pitch,-10,10))):
            self.pose[key]+=head_alpha*(goal-self.pose[key])
        for key,goal in (('eye_pan',clamp(yaw-self.pose['neck_pan'],-18,18)),
                         ('eye_tilt',clamp(pitch-self.pose['neck_tilt'],-12,12))):
            self.pose[key]+=eye_alpha*(goal-self.pose[key])
        return dict(self.pose)
