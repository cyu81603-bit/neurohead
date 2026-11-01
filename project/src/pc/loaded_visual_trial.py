"""One-shot 10s external-USB-Cam response using ONLY verified 1495/1500/1505us.
Image-coordinate three-position demonstration, not calibrated eye-in-hand servoing.
"""
import argparse,hashlib,json,math,time
from pathlib import Path
from nh22 import Client,config,motion,stop,query
from vision_bridge import latest
ROOT=Path(__file__).resolve().parents[2]
GUARD=Path(r"F:\NeuroHead\workspace\neurohead_fpga_2026\data\joint_setups\eye_horizontal.json")
def visual_pulse(row,now,expected_session):
    v=row.get("vision") or {}
    if v.get("camera_index")!="USB Cam" or v.get("detector")!="yunet_2023mar":
        raise ValueError("wrong camera or detector")
    if not v.get("running") or v.get("error") or v.get("source_session_id")!=expected_session:
        raise ValueError("camera session unavailable or changed")
    for stamp in (row.get("host_monotonic_s"),v.get("frame_time")):
        if not isinstance(stamp,(int,float)) or not math.isfinite(stamp) or not 0<=now-stamp<=.75:
            raise ValueError("stale external camera frame")
    xy=v.get("target")
    if xy is None:return 1500
    if len(xy)!=2 or not all(isinstance(x,(int,float)) and math.isfinite(x) and -1<=x<=1 for x in xy):
        raise ValueError("invalid normalized target")
    return 1505 if xy[0]>.2 else 1495 if xy[0]<-.2 else 1500

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--session",type=Path,required=True);a=p.parse_args()
    session=json.loads(a.session.read_text(encoding="utf-8-sig"))
    if not session["loaded_positive_observed"] or not session["loaded_negative_observed"]:
        raise ValueError("both physical small-step observations required")
    path=Path(session["viewer_log"]);cam_session=session["camera_session"]
    def check():
        if time.time()>session["expires_epoch"]:raise RuntimeError("session expired")
        if hashlib.sha256(GUARD.read_bytes()).hexdigest()!=session["guard_sha256"]:
            raise RuntimeError("original eye state changed")
    check()
    row=latest(path)
    if (row.get("vision") or {}).get("target") is None:raise ValueError("no face for preflight")
    visual_pulse(row,time.monotonic(),cam_session)
    with a.session.with_suffix(".claimed").open("x") as f:f.write(str(time.time()))
    client=Client(bind="192.168.10.10");samples=[]
    result={"purpose":"bounded_three_position_external_camera_response","physical_observation":None,
            "camera":"USB Cam","calibrated_gaze_tracking_claimed":False}
    try:
        state=client.exchange(query())
        if state["status"] or state["active_mask"] or state["configured_mask"]!=1:
            raise RuntimeError("board not in disarmed Pin10-only state")
        seq=client.next_sequence();state=client.exchange(config(seq,0,1495,1505,1500,1,False))
        if state["sequence"]!=seq:raise RuntimeError("bounded envelope rejected")
        began=time.perf_counter()
        for i in range(200):
            check();row=latest(path)
            value=visual_pulse(row,time.monotonic(),cam_session) if i<180 else 1500
            pulses=[0]*22;pulses[0]=value;seq=client.next_sequence()
            state=client.exchange(motion(seq,1,pulses,int(time.monotonic()*1000)))
            if state["sequence"]!=seq or state["status"]&2:raise RuntimeError("visual response rejected")
            samples.append({"requested_us":value,"source_frame":row["vision"]["frame_id"],
                            "target":row["vision"]["target"],"telemetry":state})
            time.sleep(max(0,began+(i+1)*.05-time.perf_counter()))
        result["digital_checks_passed"]=True
    finally:
        try:
            result["final"]=client.exchange(stop(client.next_sequence()))
            seq=client.next_sequence();state=client.exchange(config(seq,0,1500,1500,1500,1,False))
            if state["sequence"]!=seq:raise RuntimeError("center-only restore rejected")
        finally:
            client.close();result["samples"]=samples;result["motion_frames"]=len(samples)
            result["requested_points_us"]=sorted({r["requested_us"] for r in samples})
            result["original_eye_guard_unchanged"]=hashlib.sha256(GUARD.read_bytes()).hexdigest()==session["guard_sha256"]
            a.session.with_suffix(".result.json").write_text(json.dumps(result,indent=2),encoding="utf-8")
    print(json.dumps({k:v for k,v in result.items() if k!="samples"},indent=2))
if __name__=="__main__":main()
