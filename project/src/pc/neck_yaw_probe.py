"""Finite operator-requested neck yaw test. Default dry-run, head supported."""
import argparse,hashlib,json,math,time
from pathlib import Path
from nh22 import Client,config,motion,query,stop
from neck_yaw_midpoint import ROOT,GUARD,GUARD_HASH,CHANNEL,ALLOWED_IDLE_CONFIG,acquire_run_lock
POINTS=(1500,1100,1500,1900,1500)
def plan():
    values=[];ends=[];previous=1500
    for target in POINTS:
        count=math.ceil((abs(target-previous)/100+.6)/.05)
        values.extend([target]*count);ends.append(len(values)-1);previous=target
    return values,ends

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ('run','operator-ready','head-supported'):
        parser.add_argument('--'+name,action='store_true')
    parser.add_argument('--out',type=Path);a=parser.parse_args()
    values,ends=plan()
    result=dict(purpose='neck_yaw_loaded_operator_span',channel=CHANNEL,connector='J10 Pin21',
        planned_points_us=list(POINTS),planned_duration_s=len(values)*.05,
        hardware_slew_us_per_frame=2,physical_observation=None,shaft_angle_measured=False,
        full_mechanical_range_verified=False)
    if not a.run:print(json.dumps(dict(dry_run=True,**result)));return
    if not (a.operator_ready and a.head_supported):raise ValueError('current wiring and supported head required')
    profile=json.loads((ROOT/'config/neck_follow.json').read_text(encoding='utf-8-sig'))
    if (not profile.get('yaw_signal_wiring_operator_confirmed')
        or profile.get('loaded_yaw_probe_requested_limits_us')!=[1100,1900]
        or not profile.get('loaded_first_pulse_digital_checks_passed')):
        raise ValueError('current wiring, first output result and exact operator requested span required')
    if hashlib.sha256(GUARD.read_bytes()).hexdigest()!=GUARD_HASH:raise ValueError('original eye guard changed')
    output=a.out or ROOT/'build'/('neck_yaw_probe_'+str(time.time_ns())+'.result.json')
    samples=[]
    with acquire_run_lock(ROOT/'build/eye_feedback.lock'):
        client=Client(bind='192.168.10.10',timeout=.1)
        try:
            state=client.exchange(query())
            if state['status'] or state['active_mask'] or state['configured_mask']&~ALLOWED_IDLE_CONFIG:
                raise RuntimeError('board not idle; no actuator writes sent')
        except BaseException:client.close();raise
        try:
            seq=client.next_sequence();state=client.exchange(config(seq,CHANNEL,1100,1900,1500,2,False))
            if state['sequence']!=seq:raise RuntimeError('configuration not acknowledged')
            started=time.perf_counter();previous_tick=started
            for i,value in enumerate(values):
                now=time.perf_counter()
                if now-started>24 or now-previous_tick>.2:raise RuntimeError('neck probe timing exceeded')
                previous_tick=now
                if hashlib.sha256(GUARD.read_bytes()).hexdigest()!=GUARD_HASH:raise RuntimeError('original eye guard changed')
                pulses=[0]*22;pulses[CHANNEL]=value;seq=client.next_sequence()
                state=client.exchange(motion(seq,1<<CHANNEL,pulses,int(time.monotonic()*1000)))
                if state['sequence']!=seq or state['status']&~5 or state['active_mask']&~(1<<CHANNEL):
                    raise RuntimeError('neck command rejected')
                samples.append(dict(requested_us=value,output_pwm_setting_us=state['output_us'][CHANNEL]))
                time.sleep(max(0,started+(i+1)*.05-time.perf_counter()))
            reached=[samples[i]['output_pwm_setting_us'] for i in ends]
            result['digital_endpoints_us']=reached
            if reached!=list(POINTS):raise RuntimeError('neck PWM endpoints not reached')
            result['digital_checks_passed']=True
        except BaseException as exc:
            result['interruption_reason']=str(exc);raise
        finally:
            try:
                state=client.exchange(stop(client.next_sequence()))
                if state['active_mask'] or state['status']:raise RuntimeError('stop not acknowledged')
                seq=client.next_sequence();state=client.exchange(config(seq,CHANNEL,1500,1500,1500,1,False))
                if state['sequence']!=seq or state['active_mask']:raise RuntimeError('center-only restore failed')
                result['final']=state
            finally:
                client.close();result.update(samples=samples,motion_frames=len(samples),
                    original_eye_guard_unchanged=hashlib.sha256(GUARD.read_bytes()).hexdigest()==GUARD_HASH)
                output.write_text(json.dumps(result,indent=2),encoding='utf-8')
    print('RESULT',output)
if __name__=='__main__':main()