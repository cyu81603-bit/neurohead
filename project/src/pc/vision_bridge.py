"""Consume existing NeuroHead viewer JSONL. Preview by default; no camera opened.
Mapping is an explicitly calibrated image-error -> pulse heuristic. It is not
a ViSP control law or measured joint-angle conversion.
"""
import argparse,json,math,time,os
from pathlib import Path
import nh22

def _latest_once(path):
    with Path(path).open("rb") as f:
        f.seek(max(0,os.fstat(f.fileno()).st_size-65536))
        for line in reversed(f.read().decode("utf-8",errors="replace").splitlines()):
            try:return json.loads(line)
            except ValueError:pass
    raise ValueError("no complete viewer sample")

def latest(path):
    # Log rotation can briefly remove the active filename; retry a few milliseconds.
    for attempt in range(4):
        try:return _latest_once(path)
        except (OSError,ValueError):
            if attempt==3:raise
            time.sleep(.005)


def sample_to_pose(sample,rows,mapping,now,session=None):
    vision=sample.get("vision") or {}
    if not vision.get("running") or vision.get("error"):
        raise ValueError("vision unavailable; stop command stream")
    for value in (sample.get("host_monotonic_s"),vision.get("frame_time")):
        if not isinstance(value,(int,float)) or not math.isfinite(value) or not 0<=now-value<=.75:
            raise ValueError("stale viewer/camera frame")
    sid=vision.get("source_session_id")
    if not sid or (session is not None and sid!=session):
        raise ValueError("camera source session changed")
    xy=vision.get("target")
    # With no face, request each mapped joint's calibrated neutral.
    if xy is not None and (len(xy)!=2 or not all(isinstance(v,(int,float)) and math.isfinite(v) and -1<=v<=1 for v in xy)):
        raise ValueError("invalid normalized face center")
    by_id={r["id"]:r for r in rows}
    values=[]
    for axis in mapping["axes"]:
        r=by_id[axis["id"]]
        if not r.get("enabled") or not r.get("mechanical_verified"):
            raise ValueError("uncalibrated mapping: "+r["id"])
        gain=axis["gain_us"]
        if type(gain) not in (int,float) or not math.isfinite(gain) or gain==0:
            raise ValueError("set a measured pulse-span and verified tracking direction")
        coord=axis["coordinate"]
        if coord not in ("x","y"):raise ValueError("coordinate must be x or y")
        error=0 if xy is None else xy[0 if coord=="x" else 1]
        pulse=round(r["neutral_us"]+gain*error)
        pulse=max(r["min_us"],min(r["max_us"],pulse))
        values.append(r["id"]+"="+str(pulse))
    mask,pulses=nh22.prepare_pose(rows,values)
    return mask,pulses,sid

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--viewer-log",required=True,type=Path)
    p.add_argument("--mapping",type=Path,default=Path(__file__).resolve().parents[2]/"config/vision_mapping.json")
    p.add_argument("--profile",type=Path,default=Path(__file__).resolve().parents[2]/"config/channels.json")
    p.add_argument("--duration",type=float,default=10)
    p.add_argument("--host",default="192.168.10.20");p.add_argument("--bind")
    p.add_argument("--execute",action="store_true")
    a=p.parse_args()
    if not 0<a.duration<=10:p.error("duration must be within 0..10 seconds")
    rows=nh22.load_profile(a.profile)
    mapping=json.loads(a.mapping.read_text(encoding="utf-8-sig"))
    if not mapping["axes"]:p.error("no calibrated vision axes configured")
    first=sample_to_pose(latest(a.viewer_log),rows,mapping,time.monotonic())
    if a.execute:nh22.assert_motion_ready(rows,first[0])
    client=nh22.Client(a.host,bind=a.bind) if a.execute else None
    session=first[2];start=time.monotonic()
    try:
        while time.monotonic()-start<a.duration:
            before=time.monotonic()
            mask,pulses,_=sample_to_pose(latest(a.viewer_log),rows,mapping,before,session)
            if client:
                nh22.assert_motion_ready(rows,mask)
                seq=client.next_sequence()
                state=client.exchange(nh22.motion(seq,mask,pulses,int(before*1000)))
                if state["sequence"]!=seq or state["status"]&2:raise RuntimeError("board rejected tracking")
            else:
                print(json.dumps({"preview":True,"mask":mask,"pulse_us":pulses}),flush=True)
            time.sleep(max(0,.02-(time.monotonic()-before)))
    finally:
        if client:client.close()
        # Stop streaming on missing/stale input; configured hardware timeout policy applies.
if __name__=="__main__":main()
