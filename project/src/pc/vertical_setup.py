"""Bounded Pin4 vertical setup. No continuous following or automatic unlocking."""
import argparse,hashlib,json,math,time
from pathlib import Path
from nh22 import Client,config,motion,query,stop
from eye_camera_feedback import acquire_run_lock
ROOT=Path(__file__).resolve().parents[2]
GUARD=Path(r"F:\NeuroHead\workspace\neurohead_fpga_2026\data\joint_setups\eye_horizontal.json")
def plan(kind,span=50):
    if kind=="neutral":return [1500]*40,[39]
    if type(span) is not int or span not in (25,50,100,150,200):raise ValueError("invalid vertical probe span")
    # PL limit 2us/20ms. Include 0.5s settling after each ramp.
    values=[];ends=[];previous=1500
    for target in (1500,1500+span,1500-span,1500):
        duration=abs(target-previous)/100+.5
        values.extend([target]*math.ceil(duration/.05));ends.append(len(values)-1);previous=target
    return values,ends
def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("kind",choices=("neutral","sweep"));p.add_argument("--span-us",type=int,default=50)
    p.add_argument("--run",action="store_true");p.add_argument("--operator-ready",action="store_true")
    p.add_argument("--profile",type=Path,default=ROOT/"config/eye_vertical.json")
    p.add_argument("--out",type=Path);a=p.parse_args()
    values,ends=plan(a.kind,a.span_us)
    if not a.run:
        print(json.dumps({"dry_run":True,"channel":1,"pin":4,"kind":a.kind,
                          "points_us":[values[i] for i in ends],"duration_s":len(values)*.05}));return
    if not a.operator_ready:p.error("current operator readiness required")
    profile=json.loads(a.profile.read_text(encoding="utf-8-sig"))
    if profile.get("channel")!=1 or not profile.get("assembled_at_1500_operator_confirmed"):
        raise ValueError("vertical neutral assembly confirmation required")
    if a.kind=="sweep":
        if not profile.get("loaded_neutral_operator_verified") or a.span_us!=profile.get("approved_probe_span_us"):
            raise ValueError("loaded neutral and exact operator-approved probe span required")
    digest=hashlib.sha256(GUARD.read_bytes()).hexdigest()
    if digest!="1051e489ce396a0d24b937b8a3dd9aaeb9a60f4fab61e0a324df33925a87ecb6":
        raise ValueError("original horizontal guard changed")
    out=a.out or ROOT/"build"/("vertical_"+a.kind+"_"+str(time.time_ns())+".result.json")
    result={"purpose":"vertical_loaded_"+a.kind,"channel":1,"connector":"J10 Pin4",
            "points_us":[values[i] for i in ends],"physical_observation":None}
    with acquire_run_lock(ROOT/"build/eye_feedback.lock"):
        client=Client(bind="192.168.10.10");samples=[]
        try:
            state=client.exchange(query())
            if state["status"] or state["active_mask"] or state["configured_mask"]!=3:
                raise RuntimeError("disarmed two-eye setup state required; no actuator writes sent")
        except BaseException:client.close();raise
        try:
            seq=client.next_sequence()
            state=client.exchange(config(seq,1,min(values),max(values),1500,2 if a.kind=="sweep" else 1,False))
            if state["sequence"]!=seq:raise RuntimeError("vertical limits rejected")
            began=time.perf_counter()
            for i,value in enumerate(values):
                if time.perf_counter()-began>12:raise RuntimeError("vertical setup deadline exceeded")
                if hashlib.sha256(GUARD.read_bytes()).hexdigest()!=digest:raise RuntimeError("horizontal guard changed")
                pulses=[0]*22;pulses[1]=value;seq=client.next_sequence()
                state=client.exchange(motion(seq,2,pulses,int(time.monotonic()*1000)))
                if state["sequence"]!=seq or state["status"]&~5 or state["active_mask"]&~2:
                    raise RuntimeError("vertical command rejected")
                samples.append({"requested_us":value,"telemetry":state})
                time.sleep(max(0,began+(i+1)*.05-time.perf_counter()))
            reached=[samples[i]["telemetry"]["output_us"][1] for i in ends]
            result["digital_endpoints_us"]=reached
            if reached!=result["points_us"]:raise RuntimeError("vertical PWM setting did not reach endpoint")
            result["digital_checks_passed"]=True
        finally:
            try:
                state=client.exchange(stop(client.next_sequence()))
                if state["active_mask"] or state["status"]:raise RuntimeError("vertical stop not acknowledged")
                seq=client.next_sequence();state=client.exchange(config(seq,1,1500,1500,1500,1,False))
                if state["sequence"]!=seq or state["active_mask"]:raise RuntimeError("vertical center-only restore failed")
                result["final"]=state
            finally:
                client.close();result["motion_frames"]=len(samples);result["samples"]=samples
                result["original_horizontal_guard_unchanged"]=hashlib.sha256(GUARD.read_bytes()).hexdigest()==digest
                out.write_text(json.dumps(result,indent=2),encoding="utf-8")
    print(json.dumps({k:v for k,v in result.items() if k!="samples"},indent=2))
if __name__=="__main__":main()
