from shared_hardware import SHARED_VISION_LOG,SHARED_VISION_STOP
"""Measure real pitch image response inside previously used 1475..1525us.
Default offline. Hold yaw at its current PWM setting; never extend travel.
"""
import argparse,hashlib,json,statistics,time
from pathlib import Path
from nh22 import Client,config,motion,query,stop
from eye_camera_feedback import acquire_run_lock
from loaded_visual_trial import visual_pulse
from vision_bridge import latest
ROOT=Path(__file__).resolve().parents[2]
GUARD=Path(r"F:\NeuroHead\workspace\neurohead_fpga_2026\data\joint_setups\eye_horizontal.json")
POINTS=(1500,1525,1500,1475,1500)
def analyze(phases,span=25):
    estimates=[];details=[]
    for phase,delta in ((1,span),(2,-span),(3,-span),(4,span)):
        rows=phases[phase]
        good=[r for r in rows if r.get("scene_motion",{}).get("valid")]
        if len(good)<8 or len(good)<.6*len(rows):
            raise ValueError("insufficient background motion frames")
        dy=sum(r["scene_motion"]["dy_px"] for r in good)
        dx=sum(r["scene_motion"]["dx_px"] for r in good)
        details.append({"phase":phase,"delta_us":delta,"unique_valid_frames":len(good),
                        "scene_dx_px":dx,"scene_dy_px":dy,"normalized_dy_per_us":dy/(240*delta)})
        if abs(dy)>=2:estimates.append(dy/(240*delta))
    if len(estimates)<3:
        return {"valid":False,"reason":"little or no measured pitch-camera response",
                "phases":details}
    median=statistics.median(estimates)
    agree=[v for v in estimates if v*median>0]
    if len(agree)<3 or max(abs(v) for v in agree)/min(abs(v) for v in agree)>4:
        return {"valid":False,"reason":"inconsistent physical image response","phases":details}
    return {"valid":True,"measured_image_dy_per_us":statistics.median(agree),
            "reverse_required":median<0,"phases":details}
def camera_records(path,sid,starts,ended):
    found={}
    for p in (path,Path(str(path)+".1"),Path(str(path)+".2")):
        if not p.exists():continue
        with p.open("rb") as f:
            f.seek(max(0,p.stat().st_size-524288))
            for line in f.read().decode("utf-8",errors="replace").splitlines():
                try:r=json.loads(line);v=r["vision"]
                except (ValueError,KeyError):continue
                stamp=v.get("frame_time",0)
                if v.get("source_session_id")==sid and starts[0]<=stamp<=ended:
                    found[v["frame_id"]]=r
    phases=[[] for _ in starts]
    for r in found.values():
        stamp=r["vision"]["frame_time"]
        phase=max(i for i,t in enumerate(starts) if stamp>=t)
        phases[phase].append(r)
    return phases
def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--run",action="store_true");p.add_argument("--operator-ready",action="store_true")
    p.add_argument("--span-us",type=int,choices=(25,50),default=25)
    p.add_argument("--hardware-step-us",type=int,choices=(1,2,10),default=1)
    a=p.parse_args()
    points=(1500,1500+a.span_us,1500,1500-a.span_us,1500)
    per_phase=40 if a.span_us==50 else 30
    if not a.run:
        print(json.dumps({"dry_run":True,"pitch_points_us":points,"seconds":per_phase*.25,"hardware_step_us":a.hardware_step_us,"mask":3,
                          "yaw":"hold current PWM setting"}));return
    if not a.operator_ready:p.error("current operator readiness required")
    digest=hashlib.sha256(GUARD.read_bytes()).hexdigest()
    if digest!="1051e489ce396a0d24b937b8a3dd9aaeb9a60f4fab61e0a324df33925a87ecb6":
        raise ValueError("original guard changed")
    log=SHARED_VISION_LOG;r=latest(log);sid=r["vision"]["source_session_id"]
    visual_pulse(r,time.monotonic(),sid)
    if not r.get("scene_motion",{}).get("valid"):raise ValueError("background motion telemetry required")
    out=ROOT/"build"/("pitch_response_"+str(time.time_ns())+".result.json")
    result={"purpose":"measured_pitch_camera_response","points_us":points,"hardware_step_us":a.hardware_step_us,"physical_observation":None}
    with acquire_run_lock(ROOT/"build/eye_feedback.lock"):
        client=Client(bind="192.168.10.10");samples=[];starts=[]
        try:
            state=client.exchange(query());yaw=state["output_us"][0]
            if state["status"] or state["active_mask"] or state["configured_mask"]!=3 or not 1100<=yaw<=1900:
                raise RuntimeError("disarmed eye setup required; no actuator writes sent")
        except BaseException:client.close();raise
        result["held_yaw_pwm_setting_us"]=yaw
        print("START_PITCH_RESPONSE_SECONDS",per_phase*.25,out,flush=True)
        try:
            for ch,lo,hi,step in ((0,1100,1900,10),(1,1500-a.span_us,1500+a.span_us,a.hardware_step_us)):
                seq=client.next_sequence();state=client.exchange(config(seq,ch,lo,hi,1500,step,False))
                if state["sequence"]!=seq:raise RuntimeError("probe configuration rejected")
            began=time.perf_counter()
            for i in range(per_phase*5):
                phase=i//per_phase
                if i%per_phase==0:starts.append(time.monotonic())
                if hashlib.sha256(GUARD.read_bytes()).hexdigest()!=digest:raise RuntimeError("guard changed")
                row=latest(log);visual_pulse(row,time.monotonic(),sid)
                seq=client.next_sequence();values=[yaw,points[phase]]+[0]*19
                state=client.exchange(motion(seq,3,values,int(time.monotonic()*1000)))
                if state["sequence"]!=seq or state["status"]&~5 or state["active_mask"]&~3:
                    raise RuntimeError("probe command rejected")
                samples.append({"phase":phase,"requested_pitch_us":points[phase],
                                "pitch_pwm_setting_us":state["output_us"][1],
                                "source_frame":row["vision"]["frame_id"]})
                time.sleep(max(0,began+(i+1)*.05-time.perf_counter()))
            ended=time.monotonic()
            endpoints=[samples[i]["pitch_pwm_setting_us"] for i in (per_phase*(phase+1)-1 for phase in range(5))]
            if endpoints!=list(points):raise RuntimeError("probe endpoints not reached")
            result["digital_endpoints_us"]=endpoints;result["digital_checks_passed"]=True
            result["image_response"]=analyze(camera_records(log,sid,starts,ended),a.span_us)
        finally:
            try:
                state=client.exchange(stop(client.next_sequence()))
                if state["active_mask"] or state["status"]:raise RuntimeError("probe stop not acknowledged")
                for ch in (0,1):
                    seq=client.next_sequence();state=client.exchange(config(seq,ch,1500,1500,1500,1,False))
                    if state["sequence"]!=seq:raise RuntimeError("center-only restore failed")
                result["final"]=state
            finally:
                client.close();result["motion_frames"]=len(samples);result["samples"]=samples
                result["original_guard_unchanged"]=hashlib.sha256(GUARD.read_bytes()).hexdigest()==digest
                out.write_text(json.dumps(result,indent=2),encoding="utf-8")
        print(json.dumps({k:v for k,v in result.items() if k!="samples"},indent=2))
if __name__=="__main__":main()
