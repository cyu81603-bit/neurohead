from shared_hardware import SHARED_VISION_LOG,SHARED_VISION_STOP
"""Finite local neck identification, eyes held at center; default no IO."""
import argparse,hashlib,json,math,time
from pathlib import Path
from nh22 import Client,config,motion,query,stop
from neck_yaw_midpoint import ROOT,GUARD,GUARD_HASH,ALLOWED_IDLE_CONFIG,acquire_run_lock
from neck_identification import CHANNELS,MASK,plan,analyze
from vision_bridge import latest
from loaded_visual_trial import visual_pulse

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ('run','operator-ready','head-supported','show'):parser.add_argument('--'+name,action='store_true')
    parser.add_argument('--out',type=Path);a=parser.parse_args();phases=plan()
    if not a.run:
        print(json.dumps(dict(dry_run=True,phases=phases,channels=list(CHANNELS),duration_s=sum(p['duration_s'] for p in phases))));return
    if not (a.operator_ready and a.head_supported):raise ValueError('current readiness and head support required')
    profile=json.loads((ROOT/'config/neck_follow.json').read_text(encoding='utf-8-sig'))
    if not profile.get('pair_common_loaded_span_operator_verified'):raise ValueError('observed common-mode loaded motion required')
    if not profile.get('eye_camera_rigidly_on_head_operator_confirmed'):
        raise ValueError('eye-camera rigid mounting on head must be confirmed for image identification')
    row=latest(SHARED_VISION_LOG);sid=row['vision']['source_session_id']
    visual_pulse(row,time.monotonic(),sid)
    if 'scene_motion' not in row:raise ValueError('motion telemetry required before actuator IO')
    output=a.out or ROOT/'build'/('neck_identify_'+str(time.time_ns())+'.result.json')
    result=dict(purpose='local_neck_image_identification',phase_plan=phases,physical_observation=None,
        shaft_angles_measured=False);samples=[];frame_number=0;window=None;cancel=[False];label=None
    if a.show:
        import tkinter as tk
        window=tk.Tk();window.title('NeuroHead 颈部局部辨识 · 完成后保留窗口')
        label=tk.StringVar(value='准备：眼睛中位，逐只辨识颈部，行程1400–1600μs')
        tk.Label(window,textvariable=label,font=('Microsoft YaHei UI',16),wraplength=620).pack(padx=24,pady=24)
        tk.Button(window,text='停止本轮',command=lambda:cancel.__setitem__(0,True),width=20).pack(pady=15)
        window.protocol('WM_DELETE_WINDOW',lambda:cancel.__setitem__(0,True));window.update()
    with acquire_run_lock(ROOT/'build/eye_feedback.lock'):
        client=Client(bind='192.168.10.10',timeout=.1)
        try:
            state=client.exchange(query())
            if state['status'] or state['active_mask'] or state['configured_mask']&~ALLOWED_IDLE_CONFIG:
                raise RuntimeError('board not idle; no actuator writes sent')
        except BaseException:client.close();raise
        try:
            if hashlib.sha256(GUARD.read_bytes()).hexdigest()!=GUARD_HASH:raise RuntimeError('original eye guard changed')
            for channel in CHANNELS:
                seq=client.next_sequence()
                state=client.exchange(config(seq,channel,1500 if channel<2 else 1400,1500 if channel<2 else 1600,1500,2,False))
                if state['sequence']!=seq:raise RuntimeError('configuration rejected')
            start=time.perf_counter();last=start;frame_number=0;frame_seen=set();valid_baseline=set()
            names={'baseline':'先稳定中位（此段不是辨识动作）','yaw':'左右转头','left':'Pin22左侧舵机','right':'Pin23右侧舵机'}
            for phase_id,phase in enumerate(phases):
                if phase_id==1 and len(valid_baseline)<10:raise RuntimeError('background motion quality insufficient; no test offsets sent')
                phase_start=time.perf_counter()
                for i in range(math.ceil(phase['duration_s']/.05)):
                    now=time.perf_counter()
                    if now-last>.2 or now-start>35:raise RuntimeError('identification deadline exceeded')
                    last=now
                    if window is not None:
                        key=phase['name'].split('_')[0]
                        title='回到中位' if key=='return' else names.get(key,key)
                        label.set(title+'\n颈部PWM：'+str(phase['pose'])+'\n约剩余 %.1f 秒'%max(0,phase['duration_s']-(now-phase_start)))
                        window.update()
                    if cancel[0]:raise RuntimeError('operator stopped identification')
                    row=latest(SHARED_VISION_LOG);visual_pulse(row,time.monotonic(),sid)
                    frame=row['vision']['frame_id'];flow=row.get('scene_motion') or {}
                    if frame not in frame_seen:
                        frame_seen.add(frame)
                        samples.append(dict(phase=phase_id,frame_id=frame,scene_motion=flow))
                        if phase_id==0 and i>=20 and flow.get('valid'):valid_baseline.add(frame)
                    values=[0]*22;values[0]=values[1]=1500
                    for channel,value in zip((18,19,20),phase['pose']):values[channel]=value
                    seq=client.next_sequence();state=client.exchange(motion(seq,MASK,values,int(time.monotonic()*1000)))
                    if state['sequence']!=seq or state['status']&~5 or state['active_mask']&~MASK:raise RuntimeError('command rejected')
                    frame_number+=1;time.sleep(max(0,phase_start+(i+1)*.05-time.perf_counter()))
                if [state['output_us'][c] for c in (18,19,20)]!=phase['pose']:raise RuntimeError('pose PWM setting not reached')
            result['digital_checks_passed']=True
        except BaseException as exc:result['interruption_reason']=str(exc)
        finally:
            try:
                state=client.exchange(stop(client.next_sequence()))
                if state['active_mask'] or state['status']:raise RuntimeError('stop not acknowledged')
                for channel in CHANNELS:
                    seq=client.next_sequence();state=client.exchange(config(seq,channel,1500,1500,1500,1,False))
                    if state['sequence']!=seq or state['active_mask']:raise RuntimeError('neutral restore rejected')
                result['final']=state
            finally:
                client.close();result.update(samples=samples,motion_frames=frame_number,
                    original_eye_guard_unchanged=hashlib.sha256(GUARD.read_bytes()).hexdigest()==GUARD_HASH)
                result['identification']=analyze(phases,samples)
                output.write_text(json.dumps(result,indent=2),encoding='utf-8')
    print('RESULT',output,flush=True)
    if window is not None:
        label.set(('辨识完成' if result.get('digital_checks_passed') else '辨识中止：'+result.get('interruption_reason',''))+'\nPWM已停止。窗口保留。')
        window.protocol('WM_DELETE_WINDOW',window.destroy);window.mainloop()
if __name__=='__main__':main()