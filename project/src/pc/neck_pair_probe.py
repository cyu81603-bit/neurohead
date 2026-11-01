"""Coupled neck basis checks, always atomic; no assumed pitch/roll signs.
Default dry-run. Requires operator-observed pair midpoint before real motion.
"""
import argparse,hashlib,json,math,time
from nh22 import Client,config,motion,query,stop
from neck_yaw_midpoint import ROOT,GUARD,GUARD_HASH,ALLOWED_IDLE_CONFIG,acquire_run_lock
CHANNELS=(18,19,20)
MASK=7<<18

def plan(basis,span=50):
    if basis not in ('common','differential','left_only','right_only') or type(span) is not int or span not in (50,100,400):
        raise ValueError('unsupported coupled basis/span')
    values=[];ends=[];previous=0
    for offset in (0,span,0,-span,0):
        left=1500 if basis=='right_only' else 1500+offset
        right=1500 if basis=='left_only' else 1500+(offset if basis in ('common','right_only') else -offset)
        pose=(1500,left,right)
        count=60 if not values and basis in ('left_only','right_only') else math.ceil((abs(offset-previous)/100+.6)/.05)
        values.extend([pose]*count);ends.append(len(values)-1);previous=offset
    return values,ends

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('basis',choices=('common','differential','left_only','right_only'))
    parser.add_argument('--span-us',type=int,choices=(50,100,400),default=50)
    for name in ('run','operator-ready','head-supported'):parser.add_argument('--'+name,action='store_true')
    a=parser.parse_args();values,ends=plan(a.basis,a.span_us)
    result=dict(purpose='neck_coupled_basis_probe',basis=a.basis,span_us=a.span_us,
        points_us=[list(values[i]) for i in ends],duration_s=len(values)*.05,
        channels=list(CHANNELS),channel_mask=MASK,physical_observation=None,pair_mixing_verified=False)
    if not a.run:print(json.dumps(dict(dry_run=True,**result)));return
    if not(a.operator_ready and a.head_supported):raise ValueError('current readiness and supported head required')
    profile=json.loads((ROOT/'config/neck_follow.json').read_text(encoding='utf-8-sig'))
    if (not (profile.get('pair_midpoint_operator_verified') or profile.get('pair_first_output_no_abnormal_operator_confirmed'))
        or profile.get('pair_reference_us')!=[1500,1500]):
        raise ValueError('first pair output needs actual no-abnormal observation before motion')
    if a.span_us==400 and profile.get('pair_'+a.basis+'_requested_limits_us')!=[1100,1900]:
        raise ValueError('this exact coupled basis needs operator requested 1100..1900 limits')
    if hashlib.sha256(GUARD.read_bytes()).hexdigest()!=GUARD_HASH:raise ValueError('original eye guard changed')
    output=ROOT/'build'/('neck_pair_'+a.basis+'_'+str(time.time_ns())+'.result.json');samples=[]
    with acquire_run_lock(ROOT/'build/eye_feedback.lock'):
        client=Client(bind='192.168.10.10',timeout=.1)
        try:
            state=client.exchange(query())
            if state['status'] or state['active_mask'] or state['configured_mask']&~ALLOWED_IDLE_CONFIG:
                raise RuntimeError('board not idle; no actuator writes sent')
        except BaseException:client.close();raise
        try:
            for c in CHANNELS:
                seq=client.next_sequence()
                state=client.exchange(config(seq,c,1500 if c==18 else 1500-a.span_us,
                    1500 if c==18 else 1500+a.span_us,1500,2,False))
                if state['sequence']!=seq:raise RuntimeError('configuration not acknowledged')
            start=time.perf_counter();last=start
            for i,pose in enumerate(values):
                now=time.perf_counter()
                if now-start>len(values)*.05+3 or now-last>.2:raise RuntimeError('coupled probe timing exceeded')
                last=now;pulses=[0]*22
                for c,u in zip(CHANNELS,pose):pulses[c]=u
                seq=client.next_sequence();state=client.exchange(motion(seq,MASK,pulses,int(time.monotonic()*1000)))
                if state['sequence']!=seq or state['status']&~5 or state['active_mask']&~MASK:
                    raise RuntimeError('coupled command rejected')
                samples.append(dict(requested_us=list(pose),output_pwm_us=[state['output_us'][c] for c in CHANNELS]))
                time.sleep(max(0,start+(i+1)*.05-time.perf_counter()))
            result['digital_endpoints_us']=[samples[i]['output_pwm_us'] for i in ends]
            if result['digital_endpoints_us']!=result['points_us']:raise RuntimeError('coupled endpoints not reached')
            result['digital_checks_passed']=True
        except BaseException as exc:result['interruption_reason']=str(exc);raise
        finally:
            try:
                state=client.exchange(stop(client.next_sequence()))
                if state['active_mask'] or state['status']:raise RuntimeError('stop not acknowledged')
                for c in CHANNELS:
                    seq=client.next_sequence();state=client.exchange(config(seq,c,1500,1500,1500,1,False))
                    if state['sequence']!=seq or state['active_mask']:raise RuntimeError('neutral restore rejected')
                result['final']=state
            finally:
                client.close();result.update(samples=samples,motion_frames=len(samples),
                    original_eye_guard_unchanged=hashlib.sha256(GUARD.read_bytes()).hexdigest()==GUARD_HASH)
                output.write_text(json.dumps(result,indent=2),encoding='utf-8')
    print('RESULT',output)
if __name__=='__main__':main()