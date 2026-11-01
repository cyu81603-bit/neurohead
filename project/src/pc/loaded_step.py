"""One-use, 2s loaded Pin10 eye check: only +/-5us around verified neutral."""
import argparse,hashlib,json,time
from pathlib import Path
from nh22 import Client,config,motion,stop,query
ROOT=Path(__file__).resolve().parents[2]
GUARD=Path(r"F:\NeuroHead\workspace\neurohead_fpga_2026\data\joint_setups\eye_horizontal.json")
def frames(delta):
    if delta not in (-5,5):raise ValueError("only +/-5us")
    return [1500]*8+[1500+delta]*16+[1500]*16
def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--session",required=True,type=Path);a=p.parse_args()
    session=json.loads(a.session.read_text(encoding="utf-8-sig"))
    delta=session["delta_us"]
    values=frames(delta)
    def check():
        if time.time()>session["expires_epoch"]:raise RuntimeError("session expired")
        if hashlib.sha256(GUARD.read_bytes()).hexdigest()!=session["guard_sha256"]:
            raise RuntimeError("original eye record changed")
    if not session.get("loaded_neutral_operator_confirmed"):raise RuntimeError("no loaded neutral evidence")
    check()
    with a.session.with_suffix(".claimed").open("x") as f:f.write(str(time.time()))
    client=Client(bind="192.168.10.10");samples=[]
    result={"purpose":"bounded_loaded_eye_requalification","delta_us":delta,
            "physical_observation":None,"max_motion_frames":40}
    try:
        state=client.exchange(query())
        if state["status"] or state["active_mask"] or state["configured_mask"]!=1:
            raise RuntimeError("board not disarmed Pin10-only")
        seq=client.next_sequence()
        state=client.exchange(config(seq,0,min(1500,1500+delta),max(1500,1500+delta),1500,1,False))
        if state["sequence"]!=seq:raise RuntimeError("small-step envelope rejected")
        began=time.perf_counter()
        for i,value in enumerate(values):
            check();pulses=[0]*22;pulses[0]=value;seq=client.next_sequence()
            state=client.exchange(motion(seq,1,pulses,int(time.monotonic()*1000)))
            if state["sequence"]!=seq or state["status"]&2:raise RuntimeError("small-step rejected")
            samples.append({"requested_us":value,"telemetry":state})
            time.sleep(max(0,began+(i+1)*.05-time.perf_counter()))
        result["digital_endpoints_us"]=[samples[i]["telemetry"]["output_us"][0] for i in (7,23,39)]
        if result["digital_endpoints_us"]!=[1500,1500+delta,1500]:
            raise RuntimeError("bounded endpoints not reached")
        result["digital_checks_passed"]=True
    finally:
        try:
            result["final"]=client.exchange(stop(client.next_sequence()))
            seq=client.next_sequence()
            state=client.exchange(config(seq,0,1500,1500,1500,1,False))
            if state["sequence"]!=seq:raise RuntimeError("center-only restore failed")
        finally:
            client.close();result["motion_commands_sent"]=len(samples);result["samples"]=samples
            result["original_eye_guard_unchanged"]=hashlib.sha256(GUARD.read_bytes()).hexdigest()==session["guard_sha256"]
            a.session.with_suffix(".result.json").write_text(json.dumps(result,indent=2),encoding="utf-8")
    print(json.dumps({k:v for k,v in result.items() if k!="samples"},indent=2))
if __name__=="__main__":main()
