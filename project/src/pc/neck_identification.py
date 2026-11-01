"""Local neck image-response identification; no ideal tendon mixing assumed."""
import math,statistics
CHANNELS=(0,1,18,19,20)
MASK=3|(7<<18)
def plan(span=100):
    if span!=100:raise ValueError('local identification uses fixed 100us increments')
    phases=[dict(name='baseline',pose=[1500]*3,duration_s=3.,motor=None,delta_us=0)]
    for motor in range(3):
        for direction in (1,-1):
            pose=[1500]*3;pose[motor]+=span*direction
            phases.append(dict(name=('yaw','left','right')[motor]+('_positive' if direction>0 else '_negative'),
                pose=pose,duration_s=2.2,motor=motor,delta_us=span*direction))
            phases.append(dict(name='return_'+('yaw','left','right')[motor],pose=[1500]*3,
                duration_s=2.2,motor=motor,delta_us=-span*direction))
    return phases

def analyze(phases,samples):
    totals=[];used=set()
    for i,phase in enumerate(phases):
        rows=[]
        for sample in samples:
            if sample['phase']!=i or sample['frame_id'] in used:continue
            used.add(sample['frame_id']);flow=sample.get('scene_motion') or {}
            if not flow.get('valid') or not 0<flow.get('dt_s',0)<.2:continue
            if any(not isinstance(flow.get(k),(int,float)) or not math.isfinite(flow[k]) for k in ('dx_px','dy_px','roll_deg')):continue
            rows.append(flow)
        totals.append(dict(phase=i,name=phase['name'],valid_frames=len(rows),
            coverage_s=sum(r['dt_s'] for r in rows),
            image_motion=[sum(r['dx_px']/320 for r in rows),sum(r['dy_px']/240 for r in rows),
                sum(math.radians(r['roll_deg']) for r in rows)]))
    vectors=[[] for _ in range(3)]
    for phase,total in zip(phases[1:],totals[1:]):
        if total['valid_frames']>=8 and total['coverage_s']>=.6*phase['duration_s']:
            vectors[phase['motor']].append([v/phase['delta_us'] for v in total['image_motion']])
    if any(len(v)<3 for v in vectors):return dict(valid=False,reason='insufficient reliable image-motion coverage',phases=totals)
    columns=[[statistics.median(v[i] for v in vv) for i in range(3)] for vv in vectors]
    J=[[columns[c][r] for c in range(3)] for r in range(3)]
    norms=[math.sqrt(sum(x*x for x in c)) for c in columns]
    if min(norms)<.00005:return dict(valid=False,reason='one or more actuator image responses too weak',phases=totals,jacobian=J)
    consistency=[sum(sum(x*y for x,y in zip(v,c))>0 for v in vv)/len(vv) for vv,c in zip(vectors,columns)]
    a,b,c=J[0];d,e,f=J[1];g,h,i=J[2]
    determinant=a*(e*i-f*h)-b*(d*i-f*g)+c*(d*h-e*g)
    separation=abs(determinant)/math.prod(norms)
    result=dict(valid=False,phases=totals,jacobian=J,
        outputs=['normalized_image_x','normalized_image_y','image_roll_radians'],
        columns=['yaw_pin21','left_pin22','right_pin23'],direction_consistency=consistency,
        normalized_volume=separation,local_reference_us=[1500]*3)
    if min(consistency)<.75:result['reason']='actuator response direction inconsistent';return result
    if separation<.1:result['reason']='observed actuator responses do not separate three independent image axes';return result
    inverse=[[v/determinant for v in row] for row in ((e*i-f*h,c*h-b*i,b*f-c*e),(f*g-d*i,a*i-c*g,c*d-a*f),(d*h-e*g,b*g-a*h,a*e-b*d))]
    condition_inf=max(sum(abs(v) for v in row) for row in J)*max(sum(abs(v) for v in row) for row in inverse)
    result.update(valid=True,inverse_jacobian=inverse,condition_number_inf=condition_inf,
        scope='local image response only, not shaft angles or global kinematics')
    return result