"""Finite MG995 diagnostic; unloaded sweep or mounted position check, dry-run by default."""
import argparse,json,time,math
from pathlib import Path
from nh22 import config,motion,query,stop
from head_transport import HeadClient
from board_restart import live_controllers
from eye_camera_feedback import acquire_run_lock

ROOT=Path(__file__).resolve().parents[2]
def trajectory(cycles=2,position_check=False,mounted_target=None,mounted_rate=200,mounted_settle=.5,mounted_reference=1500,mounted_quantum=1,mounted_target_hold=.5,return_reference=True):
    position=1500;frames=[]
    waypoints=[(1500,.6)]+[(target,.8) for _ in range(cycles) for target in (1200,1800)]+[(1500,.6)]
    if position_check:waypoints=[(1500,.6),(1200,2),(1500,2),(1800,2),(1500,.6)]
    if mounted_target is not None:position=mounted_reference;waypoints=[(mounted_reference,mounted_settle),(mounted_target,mounted_target_hold),(mounted_reference,mounted_settle)]
    if mounted_target is not None and not return_reference:waypoints=waypoints[:-1]
    slew=round(mounted_rate*.02) if mounted_target is not None else 6
    for target,hold in waypoints:
        while position!=target:
            if mounted_target is not None and mounted_quantum>1:
                remaining=abs(target-position)
                delta=remaining if remaining<2*mounted_quantum else mounted_quantum
                wait=max(1,math.ceil(delta/(mounted_rate*.02)))
                frames.extend([position]*(wait-1))
                position+=delta if target>position else -delta
                frames.append(position)
            else:position+=max(-slew,min(slew,target-position));frames.append(position)
        frames.extend([target]*round(hold/.02))
    return frames

def main():
    p=argparse.ArgumentParser(description=__doc__)
    for flag in ('run','unloaded','powered','supported'):p.add_argument('--'+flag,action='store_true')
    p.add_argument('--pin',type=int,choices=(24,4),default=24)
    p.add_argument('--cycles',type=int,choices=(1,2,3),default=2)
    p.add_argument('--pin4-mg995-confirmed','--pin4-servo-confirmed',dest='pin4_mg995_confirmed',action='store_true')
    p.add_argument('--test-model',choices=('MG995','MG90S'),default='MG995')
    p.add_argument('--position-check',action='store_true')
    p.add_argument('--mounted-no-strain',action='store_true')
    p.add_argument('--single-position',type=int,choices=(1200,1300,1500,1525,1550,1800))
    p.add_argument('--single-hold',type=float,default=5,help='Single-position output duration: unloaded 0.2..30s, mounted 0.2..5s')
    p.add_argument('--mounted-target',type=int,help='Operator-selected mounted target, ramp from/to mounted reference')
    p.add_argument('--finish-at-target',action='store_true',help='Mounted target trial stops at target without automatic return')
    p.add_argument('--mounted-reference',type=int,default=1500)
    p.add_argument('--mounted-quantum',type=int,choices=(1,10),default=1,help='Diagnostic paced step; 1 retains continuous small-step behavior')
    p.add_argument('--mounted-target-hold',type=float,default=.5)
    p.add_argument('--mounted-rate',type=int,choices=(100,150,200,500),default=200)
    p.add_argument('--mounted-settle',type=float,default=.5,help='Hold reference before and after mounted movement, 0.5..6 seconds')
    p.add_argument('--pulse-sweep-500ms',action='store_true',help='Unloaded only: 800,1000,...,2200us, each 500ms')
    p.add_argument('--upper-sweep-500ms',action='store_true',help='Unloaded only: 1800 through 2400us and back, each 500ms')
    p.add_argument('--stable-window-check',action='store_true',help='Unloaded MG995 bounded return check, 8s holds, 100us/s')
    p.add_argument('--window-reference',type=int,default=1200)
    p.add_argument('--window-target',type=int,default=1300)
    p.add_argument('--unloaded-seek-target',type=int,help='Unloaded MG995 reference search, no automatic return')
    p.add_argument('--unloaded-seek-reference',type=int,default=1200)
    p.add_argument('--fixed-point-check',action='store_true',help='Mounted MG995 Pin24 only: fixed1300-1200-1300, hold3s, at most100us transition per frame')
    a=p.parse_args()
    if a.fixed_point_check and not (a.position_check and a.mounted_no_strain and not a.unloaded and a.pin==24 and a.test_model=='MG995' and a.single_position is None and a.mounted_target is None and not a.stable_window_check and a.unloaded_seek_target is None and not a.pulse_sweep_500ms and not a.upper_sweep_500ms):p.error('Fixed-point check requires mounted MG995 Pin24, no other trajectory mode')
    if a.unloaded_seek_target is not None and not (a.unloaded and not a.mounted_no_strain and a.test_model=='MG995' and a.single_position is None and a.mounted_target is None and not a.stable_window_check and not a.pulse_sweep_500ms and not a.upper_sweep_500ms and 1000<=a.unloaded_seek_reference<=1400 and 1000<=a.unloaded_seek_target<=1400 and 0<abs(a.unloaded_seek_target-a.unloaded_seek_reference)<=100):p.error('Seek requires unloaded MG995 only, no other mode, 1000..1400us endpoints and at most100us change')
    if a.stable_window_check and not (a.unloaded and not a.mounted_no_strain and a.test_model=='MG995' and a.single_position is None and a.mounted_target is None and a.unloaded_seek_target is None and not a.pulse_sweep_500ms and not a.upper_sweep_500ms and 1000<=a.window_reference<=1400 and 1000<=a.window_target<=1400 and 0<abs(a.window_reference-a.window_target)<=100):p.error('Stable-window check requires unloaded MG995, 1000..1400us endpoints, at most100us span, and no other trajectory mode')
    if a.test_model=='MG90S' and not (a.unloaded and not a.mounted_no_strain and a.pin==4 and a.single_position==1500 and a.mounted_target is None and not a.pulse_sweep_500ms and not a.upper_sweep_500ms):p.error('MG90S control trial requires unloaded Pin4 fixed 1500us only')
    if a.finish_at_target and (a.mounted_target is None or a.unloaded):p.error('Finish-at-target requires a mounted target trial')
    sweeping=a.pulse_sweep_500ms or a.upper_sweep_500ms
    if a.pulse_sweep_500ms and a.upper_sweep_500ms:p.error('Choose one sweep mode')
    hold_limit=30 if a.unloaded and not a.mounted_no_strain else 5
    if not .2<=a.single_hold<=hold_limit:p.error(f'Single-position hold must be 0.2..{hold_limit} seconds')
    if a.single_position is not None and not a.position_check:p.error('Single position requires position-check mode')
    if a.mounted_target is not None and (not a.position_check or not a.mounted_no_strain or a.single_position is not None or not 600<=a.mounted_target<=2400):p.error('Mounted target requires mounted position-check mode and a 600..2400us target')
    if not .5<=a.mounted_settle<=6:p.error('Mounted settling hold must be 0.5..6 seconds')
    if not 600<=a.mounted_reference<=2400:p.error('Mounted reference must be 600..2400us')
    if not .5<=a.mounted_target_hold<=5:p.error('Mounted target hold must be 0.5..5 seconds')
    if sweeping and (a.position_check or a.single_position is not None or a.mounted_no_strain):p.error('Unloaded sweep cannot be combined with mounted position checks')
    frames=[a.single_position]*round(a.single_hold/.02) if a.single_position is not None else trajectory(a.cycles,a.position_check,a.mounted_target,a.mounted_rate,a.mounted_settle,a.mounted_reference,a.mounted_quantum,a.mounted_target_hold,return_reference=not a.finish_at_target)
    sweep=list(range(800,2201,200))
    if a.upper_sweep_500ms:sweep=[1800,2000,2200,2300,2400,2300,2200,2000,1800]
    if sweeping:frames=[pulse for _ in range(a.cycles) for pulse in sweep for _ in range(25)]
    if a.stable_window_check:frames=trajectory(mounted_target=a.window_target,mounted_rate=100,mounted_settle=8,mounted_reference=a.window_reference,mounted_target_hold=8)
    if a.unloaded_seek_target is not None:frames=trajectory(mounted_target=a.unloaded_seek_target,mounted_rate=100,mounted_settle=2,mounted_reference=a.unloaded_seek_reference,mounted_target_hold=8,return_reference=False)
    if a.fixed_point_check:frames=[v for v in (1300,1200,1300) for _ in range(150)]
    ch=21 if a.pin==24 else 1;mask=1<<ch
    summary=dict(channel=ch,signal_pin=a.pin,model=a.test_model,position_check=a.position_check,single_position_us=a.single_position,operator_unloaded=a.unloaded,mechanically_coupled=a.mounted_no_strain,duration_s=len(frames)*.02,commanded_limits_us=[min(frames),max(frames)],return_reference_us=None if a.single_position is not None or sweeping else 1500,physical_motion_verified=False)
    if a.mounted_target is not None:summary.update(mounted_target_us=a.mounted_target,software_slew_us_per_s=a.mounted_rate,reference_settle_s=a.mounted_settle,output_quantum_us=a.mounted_quantum,target_hold_s=a.mounted_target_hold)
    if a.mounted_target is not None:summary['return_reference_us']=None if a.finish_at_target else a.mounted_reference
    if a.finish_at_target:summary['finish_at_target']=True
    if sweeping:summary.update(pulse_sequence_us=sweep,hold_ms=500,cycles=a.cycles)
    if a.stable_window_check:summary.update(stable_window_check=True,return_reference_us=a.window_reference,waypoints_us=[a.window_reference,a.window_target,a.window_reference],hold_s=8,software_slew_us_per_s=100)
    if a.unloaded_seek_target is not None:summary.update(unloaded_reference_seek=True,return_reference_us=None,seek_reference_us=a.unloaded_seek_reference,seek_target_us=a.unloaded_seek_target,hold_s=8,software_slew_us_per_s=100)
    if a.fixed_point_check:summary.update(fixed_point_check=True,return_reference_us=1300,waypoints_us=[1300,1200,1300],hold_s=3,hardware_max_change_us_per_frame=100)
    if not a.run:print(json.dumps(dict(summary,dry_run=True)));return
    if not ((a.unloaded or (a.position_check and a.mounted_no_strain and a.pin==24)) and a.powered and a.supported):p.error('Current mechanical condition/powered/supported confirmations required')
    if sweeping and not a.unloaded:p.error('Sweep requires current unloaded confirmation')
    if a.pin==4 and not a.pin4_mg995_confirmed:p.error('Pin4 trial requires confirmation that eye servo is disconnected and only the unloaded test servo is attached')
    if live_controllers():raise RuntimeError('Existing controller still active; trial sends nothing')
    prefix='servo_control_' if a.test_model=='MG90S' else ('jaw_position_' if a.position_check else 'jaw_unloaded_')
    if a.stable_window_check:prefix='jaw_window_'
    if a.unloaded_seek_target is not None:prefix='jaw_seek_'
    if a.fixed_point_check:prefix='jaw_fixed_'
    out=ROOT/'build'/(prefix+str(time.time_ns())+'.json')
    result=dict(summary,started_epoch=time.time(),samples=[],completed=False);client=None;owned=False;lock=None
    try:
        lock=acquire_run_lock(ROOT/'build/eye_feedback.lock')
        try:
            if live_controllers():raise RuntimeError('Another controller became active; trial sends nothing')
            client=HeadClient(bind='192.168.10.10',timeout=.06)
            state=client.exchange(query())
            if state['active_mask'] or state['status']:raise RuntimeError('Board not idle; trial sends no writes')
            reference=a.single_position if a.single_position is not None else 1500
            lo,hi,step=(800,2200,100) if a.pulse_sweep_500ms else (1200,1800,10)
            if a.upper_sweep_500ms:lo,hi,reference,step=1800,2400,1800,100
            if a.mounted_target is not None:lo,hi,reference,step=min(a.mounted_reference,a.mounted_target),max(a.mounted_reference,a.mounted_target),a.mounted_reference,a.mounted_rate//50
            if a.mounted_target is not None and a.mounted_quantum>1:step=max(step,2*a.mounted_quantum)
            if a.single_position==1300:lo,hi,reference,step=1200,1300,1300,2
            if a.stable_window_check:lo,hi,reference,step=min(a.window_reference,a.window_target),max(a.window_reference,a.window_target),a.window_reference,2
            if a.unloaded_seek_target is not None:lo,hi,reference,step=min(a.unloaded_seek_reference,a.unloaded_seek_target),max(a.unloaded_seek_reference,a.unloaded_seek_target),a.unloaded_seek_reference,2
            if a.fixed_point_check:lo,hi,reference,step=1200,1300,1300,100
            seq=client.next_sequence();state=client.exchange(config(seq,ch,lo,hi,reference,step,False))
            if state['sequence']!=seq or state['active_mask'] or not state['configured_mask']&mask:raise RuntimeError('Jaw idle configuration rejected')
            owned=True;due=time.monotonic()
            previous=None
            for pulse in frames:
                if time.monotonic()-due>.2:raise RuntimeError('Trial timing overrun; stop')
                pulses=[0]*22;pulses[ch]=pulse;seq=client.next_sequence()
                state=client.exchange(motion(seq,mask,pulses))
                if state['sequence']!=seq or state['status']&~5 or state['active_mask']&~mask:raise RuntimeError('Unexpected board acknowledgement')
                result['samples'].append(dict(t=time.monotonic(),target=pulse,output=state['output_us'][ch],mask=state['active_mask']))
                if a.position_check and pulse in (1200,1300,1500,1525,1550,1800,a.mounted_reference,a.mounted_target,a.unloaded_seek_target,a.window_reference,a.window_target) and pulse!=previous:print('POSITION_US='+str(pulse),flush=True)
                if sweeping and pulse!=previous:print('SWEEP_US='+str(pulse),flush=True)
                previous=pulse
                due+=.02;time.sleep(max(0,due-time.monotonic()))
            result['completed']=True
            # Only this jaw channel was ever enabled; the head remains supported.
            state=client.exchange(stop(client.next_sequence()));owned=False
            if state['active_mask'] or state['status']:raise RuntimeError('PWM-off confirmation failed')
            result['pwm_off_confirmed']=True
        finally:
            if client and owned:
                state=client.exchange(stop(client.next_sequence()));owned=False
                result['pwm_off_confirmed']=not(state['active_mask'] or state['status'])
    except BaseException as exc:
        result['error']=str(exc);raise
    finally:
        if client:
            try:
                if owned:
                    state=client.exchange(stop(client.next_sequence()));result['pwm_off_confirmed']=not(state['active_mask'] or state['status'])
            finally:client.close()
        if lock:lock.close()
        result['completed_epoch']=time.time();out.write_text(json.dumps(result,indent=2),encoding='utf-8')
    outputs=[r['output'] for r in result['samples']]
    print(json.dumps(dict(summary,completed=result['completed'],frames=len(outputs),telemetry_output_limits_us=[min(outputs),max(outputs)],pwm_off_confirmed=result.get('pwm_off_confirmed'),result_path=str(out))))

if __name__=='__main__':main()
