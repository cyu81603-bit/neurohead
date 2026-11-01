"""10s visible eye response on USB Cam within observed span, default offline.
Uses image horizontal position, not native ViSP or measured gaze feedback.
Requires successful same-linkage span evidence and a fresh one-use operator session.
"""
import argparse, hashlib, json, math, time
from pathlib import Path
from nh22 import Client, config, motion, query, stop
from loaded_visual_trial import visual_pulse
from vision_bridge import latest

ROOT=Path(__file__).resolve().parents[2]
GUARD=Path(r"F:\NeuroHead\workspace\neurohead_fpga_2026\data\joint_setups\eye_horizontal.json")
LO,HI,NEUTRAL=1100,1900,1500

def visible_pulse(row, now, camera_session, polarity=1):
    # Reuse the existing strict device/session/freshness/target validator.
    visual_pulse(row,now,camera_session)
    if type(polarity) is not int or polarity not in (-1,1):
        raise ValueError("polarity must be +/-1")
    xy=row["vision"]["target"]
    if xy is None or abs(xy[0])<=.08:return NEUTRAL
    x=xy[0]
    magnitude=min(1.0,(abs(x)-.08)/(.60-.08))
    return NEUTRAL+polarity*(1 if x>0 else -1)*round(400*magnitude)

def validate_evidence(session):
    evidence_path=Path(session["span_evidence"])
    raw=evidence_path.read_bytes()
    if hashlib.sha256(raw).hexdigest()!=session["span_evidence_sha256"]:
        raise ValueError("span evidence changed")
    evidence=json.loads(raw)
    if (evidence.get("purpose")!="finite_same_linkage_visible_span_check"
        or evidence.get("limits_us")!=[1000,2000]
        or evidence.get("digital_checks_passed") is not True
        or evidence.get("operator_smooth_bidirectional_return_confirmed") is not True
        or not evidence.get("physical_observation")
        or evidence.get("original_eye_guard_unchanged") is not True):
        raise ValueError("same-linkage smooth visible span evidence required")

def run(session_path):
    session=json.loads(session_path.read_text(encoding="utf-8-sig"))
    if session.get("operator_ready") is not True:
        raise ValueError("current operator ready confirmation required")
    validate_evidence(session)
    polarity=session.get("polarity",1)
    path=Path(session["viewer_log"])
    camera_session=session["camera_session"]
    def check():
        remaining=session["expires_epoch"]-time.time()
        if not 0<remaining<=120:raise RuntimeError("session expired or invalid")
        if hashlib.sha256(GUARD.read_bytes()).hexdigest()!=session["guard_sha256"]:
            raise RuntimeError("original eye guard changed")
    check()
    row=latest(path)
    if (row.get("vision") or {}).get("target") is None:
        raise ValueError("face required before starting")
    visible_pulse(row,time.monotonic(),camera_session,polarity)
    with session_path.with_suffix(".claimed").open("x",encoding="utf-8") as f:f.write(str(time.time()))
    samples=[]
    result={"purpose":"visible_external_camera_eye_response","camera":"USB Cam",
            "limits_us":[LO,HI],"span_evidence":session["span_evidence"],
            "polarity":polarity,"physical_observation":None,
            "calibrated_gaze_tracking_claimed":False}
    client=Client(bind="192.168.10.10")
    try:
        state=client.exchange(query())
        if state["status"] or state["active_mask"] or state["configured_mask"]!=1:
            raise RuntimeError("board must be disarmed with Pin10-only configuration")
        seq=client.next_sequence()
        state=client.exchange(config(seq,0,LO,HI,NEUTRAL,10,False))
        if state["sequence"]!=seq:raise RuntimeError("visible envelope rejected")
        began=time.perf_counter()
        for i in range(200):
            check()
            row=latest(path)
            value=visible_pulse(row,time.monotonic(),camera_session,polarity) if i<180 else NEUTRAL
            pulses=[0]*22;pulses[0]=value;seq=client.next_sequence()
            state=client.exchange(motion(seq,1,pulses,int(time.monotonic()*1000)))
            if state["sequence"]!=seq or state["status"] & ~5 or state["active_mask"] & ~1:
                raise RuntimeError("unexpected sequence, fault or active channel")
            samples.append({"requested_us":value,"source_frame":row["vision"]["frame_id"],
                            "target":row["vision"]["target"],"telemetry":state})
            time.sleep(max(0,began+(i+1)*.05-time.perf_counter()))
        if samples[-1]["telemetry"]["output_us"][0]!=NEUTRAL:
            raise RuntimeError("neutral PWM setting not reached at end")
        result["digital_checks_passed"]=True
    finally:
        try:
            state=client.exchange(stop(client.next_sequence()))
            if state["active_mask"] or state["status"]:raise RuntimeError("stop not acknowledged")
            seq=client.next_sequence()
            state=client.exchange(config(seq,0,NEUTRAL,NEUTRAL,NEUTRAL,1,False))
            if state["sequence"]!=seq or state["active_mask"]:raise RuntimeError("center-only restore rejected")
            result["final"]=state
        finally:
            client.close()
            result["motion_frames"]=len(samples)
            result["requested_range_us"]=[min(s["requested_us"] for s in samples),max(s["requested_us"] for s in samples)] if samples else None
            result["original_eye_guard_unchanged"]=hashlib.sha256(GUARD.read_bytes()).hexdigest()==session["guard_sha256"]
            result["samples"]=samples
            session_path.with_suffix(".result.json").write_text(json.dumps(result,indent=2),encoding="utf-8")
    print(json.dumps({k:v for k,v in result.items() if k!="samples"},indent=2))

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--run",action="store_true")
    p.add_argument("--session",type=Path)
    a=p.parse_args()
    if not a.run:
        print(json.dumps({"dry_run":True,"camera":"USB Cam","channel":0,"limits_us":[LO,HI],
                          "duration_s":10,"response_s":9,"neutral_s":1,
                          "step_us_per_20ms":10,"input":"normalized face center x",
                          "mapping":"deadband +/-0.08; proportional to +/-0.60; saturate at endpoints"},indent=2))
        return
    if a.session is None:p.error("--session is required")
    run(a.session)
if __name__=="__main__":main()
