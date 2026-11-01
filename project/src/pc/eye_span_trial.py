"""Finite visible Pin10 eye sweep, reusing the known project's ramp and dwell.
Default is offline dry-run. Loaded runs require a fresh operator session confirming
that the SAME linkage previously traversed the requested span without binding.
Does not clear the original mechanical inhibition or establish measured angles.
"""
import argparse, hashlib, json, time
from pathlib import Path
from nh22 import Client, config, motion, query, stop

GUARD = Path(r"F:\NeuroHead\workspace\neurohead_fpga_2026\data\joint_setups\eye_horizontal.json")

def plan(lo=1000, hi=2000):
    if type(lo) is not int or type(hi) is not int or not 1000 <= lo < 1500 < hi <= 2000:
        raise ValueError("span must straddle 1500us within 1000..2000us")
    # 10us per 20ms in PL. Include 400ms settling at every requested point.
    previous = 1500
    frames = []
    endpoint_indices = []
    for target in (1500, hi, lo, 1500):
        count = (abs(target - previous) + 9)//10 + 20
        frames.extend([target] * count)
        endpoint_indices.append(len(frames)-1)
        previous = target
    return frames, endpoint_indices

def validate_session(session, lo, hi, now=None):
    now = time.time() if now is None else now
    if not isinstance(session.get("expires_epoch"), (int,float)) or not 0 < session["expires_epoch"]-now <= 120:
        raise ValueError("session must expire within 120s")
    if session.get("confirmed_span_us") != [lo,hi]:
        raise ValueError("requested span differs from operator-confirmed same-linkage span")
    for key in ("same_linkage_full_span_smooth_and_returned",
                "single_pin10_servo_powered_and_observable"):
        if session.get(key) is not True:
            raise ValueError("missing current physical confirmation: "+key)
    if not isinstance(session.get("operator_report"), str) or not session["operator_report"].strip():
        raise ValueError("missing actual operator report")
    if hashlib.sha256(GUARD.read_bytes()).hexdigest() != session.get("guard_sha256"):
        raise ValueError("original guard changed")

def run(session_path, lo, hi):
    session=json.loads(session_path.read_text(encoding="utf-8-sig"))
    validate_session(session,lo,hi)
    with session_path.with_suffix(".claimed").open("x",encoding="utf-8") as f:
        f.write(str(time.time()))
    values, endpoints=plan(lo,hi)
    samples=[]
    result={"purpose":"finite_same_linkage_visible_span_check",
            "limits_us":[lo,hi],"step_us_per_20ms":10,
            "physical_observation":None,"full_mechanical_calibration_claimed":False}
    client=Client(bind="192.168.10.10")
    try:
        state=client.exchange(query())
        if state["status"] or state["active_mask"] or state["configured_mask"] != 1:
            raise RuntimeError("board must be disarmed with Pin10-only configuration")
        seq=client.next_sequence()
        state=client.exchange(config(seq,0,lo,hi,1500,10,False))
        if state["sequence"] != seq:
            raise RuntimeError("finite span configuration rejected")
        began=time.perf_counter()
        for i,value in enumerate(values):
            validate_session(session,lo,hi)
            pulses=[0]*22
            pulses[0]=value
            seq=client.next_sequence()
            state=client.exchange(motion(seq,1,pulses,int(time.monotonic()*1000)))
            if state["sequence"] != seq or state["status"] & ~5 or state["active_mask"] & ~1:
                raise RuntimeError("unexpected sequence, fault or active channel")
            samples.append({"requested_us":value,"telemetry":state})
            time.sleep(max(0,began+(i+1)*.02-time.perf_counter()))
        result["digital_endpoints_us"]=[samples[i]["telemetry"]["output_us"][0] for i in endpoints]
        if result["digital_endpoints_us"] != [1500,hi,lo,1500]:
            raise RuntimeError("PWM setting failed to reach requested endpoint")
        result["digital_checks_passed"]=True
    finally:
        try:
            state=client.exchange(stop(client.next_sequence()))
            if state["active_mask"] or state["status"]:
                raise RuntimeError("PWM disarm not acknowledged")
            seq=client.next_sequence()
            state=client.exchange(config(seq,0,1500,1500,1500,1,False))
            if state["sequence"] != seq or state["active_mask"]:
                raise RuntimeError("center-only restore rejected")
            result["final"]=state
        finally:
            client.close()
            result["motion_frames"]=len(samples)
            result["samples"]=samples
            result["original_eye_guard_unchanged"]=hashlib.sha256(GUARD.read_bytes()).hexdigest()==session["guard_sha256"]
            session_path.with_suffix(".result.json").write_text(json.dumps(result,indent=2),encoding="utf-8")
    print(json.dumps({k:v for k,v in result.items() if k!="samples"},indent=2))

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--min-us",type=int,default=1000)
    p.add_argument("--max-us",type=int,default=2000)
    p.add_argument("--run",action="store_true")
    p.add_argument("--session",type=Path)
    a=p.parse_args()
    values,endpoints=plan(a.min_us,a.max_us)
    if not a.run:
        print(json.dumps({"dry_run":True,"channel":0,"connector":"J10 Pin10",
                          "points_us":[values[i] for i in endpoints],
                          "frames":len(values),"duration_s":len(values)*.02,
                          "step_us_per_20ms":10},indent=2))
        return
    if a.session is None:
        p.error("--session is required for a loaded run")
    run(a.session,a.min_us,a.max_us)
if __name__=="__main__":main()
