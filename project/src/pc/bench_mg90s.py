"""Bounded unloaded MG90S test: channel0/J10 pin10 or channel1/J10 pin4.
This diagnostic never clears the original robot-eye motion inhibition.
"""
import argparse,hashlib,json,time
from pathlib import Path
from nh22 import Client,config,motion,stop,query
from eye_camera_feedback import acquire_run_lock
POINTS=(1500,1450,1500,1550,1500)
GUARD=Path(r"F:\NeuroHead\workspace\neurohead_fpga_2026\data\joint_setups\eye_horizontal.json")
def plan(channel=1,known=False):
    if channel not in (0,1):raise ValueError("bench channel must be 0 or 1")
    frames=[]
    for pulse,count in (zip((1500,2000,1000,1500),(20,70,120,70)) if known else zip(POINTS,(30,30,30,30,30))):
        values=[0]*22;values[channel]=pulse
        frames.extend([list(values) for _ in range(count)])
    return frames
def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--run",action="store_true")
    p.add_argument("--unloaded",action="store_true")
    p.add_argument("--channel",type=int,choices=(0,1),default=0)
    p.add_argument("--out",type=Path)
    p.add_argument("--known-project-pattern",action="store_true",help="unloaded only: reproduce known 1000..2000us, 10us/frame pattern")
    a=p.parse_args();ch=a.channel;bit=1<<ch
    frames=plan(ch,a.known_project_pattern)
    points=(1500,2000,1000,1500) if a.known_project_pattern else POINTS
    endpoint_indices=(19,89,209,279) if a.known_project_pattern else (29,59,89,119,149)
    result=dict(dry_run=not a.run,channel=ch,pin=10 if ch==0 else 4,
                points_us=list(points),duration_s=len(frames)*.02,planned_frames=len(frames),
                physical_motion_observed=None,completed=False)
    if not a.run:print(json.dumps(result,indent=2));return
    if not a.unloaded:p.error("current operator unloaded confirmation required")
    original_hash=hashlib.sha256(GUARD.read_bytes()).hexdigest()
    result["original_eye_guard_sha256"]=original_hash
    with acquire_run_lock(Path(__file__).resolve().parents[2]/"build/eye_feedback.lock"):
        client=Client(bind="192.168.10.10",timeout=1);samples=[]
        try:
            state=client.exchange(query())
            if state["status"] or state["active_mask"] or state["configured_mask"]&~3:
                raise RuntimeError("not in disarmed bench state; no actuator writes sent")
        except BaseException:
            client.close()
            raise
        try:
            seq=client.next_sequence()
            state=client.exchange(config(seq,ch,1000 if a.known_project_pattern else 1450,2000 if a.known_project_pattern else 1550,1500,10 if a.known_project_pattern else 5,False))
            if state["sequence"]!=seq:raise RuntimeError("bench limits rejected")
            began=time.perf_counter()
            for i,values in enumerate(frames):
                seq=client.next_sequence()
                state=client.exchange(motion(seq,bit,values,int(time.monotonic()*1000)))
                if state["sequence"]!=seq or state["status"]&2:raise RuntimeError("command rejected")
                samples.append(dict(index=i,requested_us=values[ch],telemetry=state))
                time.sleep(max(0,began+(i+1)*.02-time.perf_counter()))
            result["digital_endpoints_us"]=[samples[i]["telemetry"]["output_us"][ch] for i in endpoint_indices]
            if result["digital_endpoints_us"]!=list(points):raise RuntimeError("PWM setting did not reach endpoints")
            result["completed"]=True
        finally:
            try:
                state=client.exchange(stop(client.next_sequence()))
                if state["active_mask"] or state["status"]:raise RuntimeError("disarm failed")
                seq=client.next_sequence()
                state=client.exchange(config(seq,ch,1500,1500,1500,1,False))
                if state["sequence"]!=seq:raise RuntimeError("center-only restore failed")
                result["final"]=state
                result["remaining_configuration"]="bench channels center-only; not mechanical calibration"
            finally:
                client.close();result["motion_commands_sent"]=len(samples);result["samples"]=samples
                result["original_eye_guard_unchanged"]=hashlib.sha256(GUARD.read_bytes()).hexdigest()==original_hash
                if a.out:a.out.write_text(json.dumps(result,indent=2),encoding="utf-8")
        print(json.dumps({k:v for k,v in result.items() if k!="samples"},indent=2))
if __name__=="__main__":main()
