"""Five-axis visual coordination math. No sockets, files or physical angle claims."""
import math,statistics
from image_feedback import Feedback
from neck_presets import neck_neutral,rod_up_signs

def pitch_limit(profile):
    n=neck_neutral(profile);return min(n[1]-1100,1900-n[1],n[2]-1100,1900-n[2],170)
def neck_pose(profile,yaw,pitch):
    n=neck_neutral(profile);signs=rod_up_signs(profile)
    if not math.isfinite(yaw) or not math.isfinite(pitch):raise ValueError('invalid neck offset')
    if abs(yaw)>400 or abs(pitch)>pitch_limit(profile):raise ValueError('neck offset outside development envelope')
    return [round(n[0]+yaw),round(n[1]+signs[0]*pitch),round(n[2]+signs[1]*pitch)]

def identification_plan(profile):
    # Hold eyes at center. Probe independent yaw and common physical rod lift.
    phases=[('baseline',0,0)]
    for name,y,p in (('yaw_positive',80,0),('yaw_negative',-80,0),('pitch_positive',0,80),('pitch_negative',0,-80)):
        phases.append((name,y,p));phases.append(('return_'+name,0,0))
    return [{'name':name,'target':[1500,1500]+neck_pose(profile,y,p),'yaw':y,'pitch':p} for name,y,p in phases]

def analyze_identification(phases,observations,reference,allow_reference_drift=False):
    medians=[]
    for i,phase in enumerate(phases):
        rows=observations.get(i,{})
        if len(rows)<5:raise ValueError('Not enough unique settled face frames in '+phase['name'])
        pairs=list(rows.values());m=[statistics.median(v[k] for v in pairs) for k in (0,1)]
        if any(statistics.median(abs(v[k]-m[k]) for v in pairs)>.045 for k in (0,1)):
            raise ValueError('Face moved during '+phase['name'])
        medians.append(m)
    centers=[medians[i] for i in range(0,len(phases),2)]
    drift=[max(v[k] for v in centers)-min(v[k] for v in centers) for k in (0,1)]
    reference_repeatable=max(drift)<=.12
    if not reference_repeatable and (not allow_reference_drift or max(drift)>.4):
        raise ValueError('Reference image drifted beyond identification envelope')
    columns=[]
    for positive,negative in ((1,3),(5,7)):
        slopes=[]
        for idx,delta in ((positive,80),(negative,-80)):
            slopes.append([(medians[idx][k]-(medians[idx-1][k]+medians[idx+1][k])/2)/delta for k in (0,1)])
        norms=[math.hypot(*v) for v in slopes]
        if min(norms)<.00015 or max(norms)>.03:raise ValueError('Neck image response too weak or too large')
        dot=sum(a*b for a,b in zip(*slopes))
        if dot<=(.8 if not reference_repeatable else .5)*norms[0]*norms[1] or max(norms)/min(norms)>3:raise ValueError('Positive and negative neck response inconsistent')
        columns.append([(a+b)/2 for a,b in zip(*slopes)])
    a,c=columns[0];b,d=columns[1];det=a*d-b*c
    if abs(det)/(math.hypot(a,c)*math.hypot(b,d))<.25:raise ValueError('Yaw and pitch image response cannot be separated')
    return {'valid':True,'jacobian':[[a,b],[c,d]],'inverse':[[d/det,-b/det],[-c/det,a/det]],
            'reference_us':list(reference),'settled_image_centers':medians,
            'reference_repeatable':reference_repeatable,'reference_drift_xy':drift,
            'provisional_direction_only':not reference_repeatable,
            'scope':'local camera response only; not shaft angles or full neck kinematics'}

class Coordinator:
    def __init__(self,profile,values):
        self.profile=profile;self.reference=neck_neutral(profile);self.last_frame=None;self.last_time=None
        self.eye=[Feedback(.002,gain=.8,max_rate=200),Feedback(-.002 if profile.get('vertical_reverse') else .002,
                  gain=.8,max_rate=100,lo=profile.get('eye_vertical_limits_us',[1000,2000])[0],
                  hi=profile.get('eye_vertical_limits_us',[1000,2000])[1])]
        for c,u in zip(self.eye,values):c.pulse=float(u)
        self.yaw=float(values[2]-self.reference[0]);self.pitch=sum((values[k+3]-self.reference[k+1])*rod_up_signs(profile)[k] for k in (0,1))/2;self.active_age=0.
    def update(self,v,values,calibration=None):
        frame=v['frame_id'];stamp=v['frame_time'];target=v['target']
        if frame==self.last_frame:return None
        dt=0 if self.last_time is None else max(0,min(.1,stamp-self.last_time))
        if self.last_frame is not None and (frame<self.last_frame or stamp<=self.last_time):raise ValueError('Camera stream reversed')
        self.last_frame=frame;self.last_time=stamp
        eyes=[c.update(frame,stamp,None if target is None else target[k]) for k,c in enumerate(self.eye)]
        self.active_age=self.active_age+dt if target is not None else 0.
        if calibration is not None:
            if not calibration.get('valid') or calibration.get('reference_us')!=self.reference:raise ValueError('Neck camera calibration reference mismatch')
            if target is not None and self.active_age>1.:
                # Slowly transfer sustained eye displacement to the neck. Signs and
                # cross-coupling come from the measured local camera response.
                offsets=[values[k]-1500 for k in (0,1)]
                image=[self.eye[k].jacobian*(u-math.copysign(60,u) if abs(u)>60 else 0)*.35 for k,u in enumerate(offsets)]
                rates=[sum(a*b for a,b in zip(row,image)) for row in calibration['inverse']]
                yaw_limit=min(400,calibration.get('automatic_yaw_limit_us',400));yaw_rate=min(50,calibration.get('automatic_yaw_rate_us_per_s',50))
                self.yaw=max(-yaw_limit,min(yaw_limit,self.yaw+max(-yaw_rate,min(yaw_rate,rates[0]))*dt))
                limit=min(pitch_limit(self.profile),calibration.get('automatic_pitch_limit_us',170));pitch_rate=min(35,calibration.get('automatic_pitch_rate_us_per_s',35))
                self.pitch=max(-limit,min(limit,self.pitch+max(-pitch_rate,min(pitch_rate,rates[1]))*dt))
            return eyes+neck_pose(self.profile,self.yaw,self.pitch)
        return eyes+list(values[2:])
def validate_direction_record(record,profile,camera_session):
    """Reuse only an accepted local result from this camera session/reference."""
    if not isinstance(record,dict) or record.get('success') is not True:raise ValueError('No saved successful neck direction')
    expected_setup=profile.get('camera_setup_signature');saved_setup=record.get('camera_setup_signature')
    if expected_setup and saved_setup!=expected_setup:raise ValueError('相机安装配置或标定参考变化，请重新辨识方向')
    if record.get('camera_session')!=camera_session and not (expected_setup and saved_setup==expected_setup and profile.get('camera_setup_operator_confirmed')):
        raise ValueError('相机预览已重启；需要确认安装未变才能沿用方向')
    cal=record.get('calibration',{})
    if cal.get('valid') is not True or cal.get('reference_us')!=neck_neutral(profile):raise ValueError('Saved direction reference changed')
    J=cal.get('jacobian');inv=cal.get('inverse')
    for matrix in (J,inv):
        if not isinstance(matrix,list) or len(matrix)!=2 or any(not isinstance(row,list) or len(row)!=2 for row in matrix):raise ValueError('Invalid saved response matrix')
        if any(type(x) not in (int,float) or not math.isfinite(x) for row in matrix for x in row):raise ValueError('Invalid saved response values')
    for i in (0,1):
        for j in (0,1):
            if abs(sum(J[i][k]*inv[k][j] for k in (0,1))-(1 if i==j else 0))>1e-6:raise ValueError('Saved matrix inverse mismatch')
    if any(not .00015<=math.hypot(J[0][i],J[1][i])<=.03 for i in (0,1)):raise ValueError('Saved response outside supported range')
    drift=cal.get('reference_drift_xy',[0.,0.])
    if len(drift)!=2 or any(type(x) not in (int,float) or not math.isfinite(x) or not 0<=x<=.4 for x in drift):raise ValueError('Saved reference drift is not eligible')
    import copy
    result=copy.deepcopy(cal)
    result.update(automatic_yaw_limit_us=100,automatic_pitch_limit_us=100,automatic_yaw_rate_us_per_s=20,automatic_pitch_rate_us_per_s=15)
    result['reused_after_preview_restart']=record.get('camera_session')!=camera_session
    return result
def camera_setup_signature(profile,camera_config):
    """Physical setup/config identity; independent of a preview process UUID."""
    import hashlib,json
    setup=dict(schema=1,camera={k:camera_config.get(k) for k in ('device_name','device_path','width','height','fps','fallback_to_builtin')},
        mount=profile.get('camera_mount'),mount_revision=profile.get('camera_mount_revision',1),
        reference_us=neck_neutral(profile),rod_up_pwm_signs=profile.get('rod_up_pwm_signs'),eye_reference_us=[1500,1500],
        pixel_pipeline='named_uvc_mjpeg_bgr_yunet_2023mar_no_image_flip')
    return hashlib.sha256(json.dumps(setup,sort_keys=True,separators=(',',':')).encode('utf-8')).hexdigest()