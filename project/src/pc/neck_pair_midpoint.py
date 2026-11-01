"""First coupled-neck pose check: all three neck PWM commands 1500us, 0.2s.
Yaw has observed midpoint; pair midpoint and mixing signs remain unverified.
"""
import argparse,hashlib,json,time
from nh22 import Client,config,motion,query,stop
from neck_yaw_midpoint import ROOT,GUARD,GUARD_HASH,ALLOWED_IDLE_CONFIG,acquire_run_lock
CHANNELS=(18,19,20)
MASK=7<<18

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ('run','operator-ready','head-supported'):parser.add_argument('--'+name,action='store_true')
    a=parser.parse_args()
    result=dict(purpose='neck_pair_initial_pose_check',channels=list(CHANNELS),channel_mask=MASK,
        pair_target_us=[1500,1500],yaw_hold_us=1500,duration_s=.2,
        physical_observation=None,pair_mechanical_neutral_verified=False,pair_mixing_verified=False,
        first_pair_shaft_positions_unknown=True)
    if not a.run:print(json.dumps(dict(dry_run=True,**result)));return
    if not (a.operator_ready and a.head_supported):raise ValueError('all three neck wiring and supported head required')
    profile=json.loads((ROOT/'config/neck_follow.json').read_text(encoding='utf-8-sig'))
    if not profile.get('yaw_reference_operator_verified') or profile.get('yaw_reference_pulse_us')!=1500:
        raise ValueError('observed yaw midpoint required')
    if hashlib.sha256(GUARD.read_bytes()).hexdigest()!=GUARD_HASH:raise ValueError('original eye guard changed')
    output=ROOT/'build'/('neck_pair_first_'+str(time.time_ns())+'.result.json');samples=[]
    with acquire_run_lock(ROOT/'build/eye_feedback.lock'):
        client=Client(bind='192.168.10.10',timeout=.1)
        try:
            state=client.exchange(query())
            if state['status'] or state['active_mask'] or state['configured_mask']&~ALLOWED_IDLE_CONFIG:
                raise RuntimeError('board not idle; no actuator writes sent')
        except BaseException:client.close();raise
        try:
            for channel in CHANNELS:
                seq=client.next_sequence();state=client.exchange(config(seq,channel,1500,1500,1500,2,False))
                if state['sequence']!=seq:raise RuntimeError('configuration not acknowledged')
            started=time.perf_counter()
            for i in range(4):
                if time.perf_counter()-started>.3:raise RuntimeError('pair first output deadline exceeded')
                values=[0]*22
                for channel in CHANNELS:values[channel]=1500
                seq=client.next_sequence();state=client.exchange(motion(seq,MASK,values,int(time.monotonic()*1000)))
                if state['sequence']!=seq or state['status']&~5 or state['active_mask']&~MASK:
                    raise RuntimeError('pair first command rejected')
                samples.append(dict(output_pwm_settings_us=[state['output_us'][c] for c in CHANNELS]))
                time.sleep(max(0,started+(i+1)*.05-time.perf_counter()))
            if samples[-1]['output_pwm_settings_us']!=[1500]*3:raise RuntimeError('PWM settings not reached')
            result['digital_checks_passed']=True
        except BaseException as exc:result['interruption_reason']=str(exc);raise
        finally:
            try:
                state=client.exchange(stop(client.next_sequence()))
                if state['active_mask'] or state['status']:raise RuntimeError('stop not acknowledged')
                result['final']=state
            finally:
                client.close();result.update(samples=samples,motion_frames=len(samples),
                    original_eye_guard_unchanged=hashlib.sha256(GUARD.read_bytes()).hexdigest()==GUARD_HASH)
                output.write_text(json.dumps(result,indent=2),encoding='utf-8')
    print('RESULT',output)
if __name__=='__main__':main()