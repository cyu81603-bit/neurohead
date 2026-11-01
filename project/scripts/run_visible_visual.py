"""Start a finite visible response only after explicit current operator readiness."""
import argparse, hashlib, json, subprocess, sys, time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"src/pc"))
from vision_bridge import latest
from visible_visual_trial import visible_pulse, GUARD

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--run",action="store_true")
    p.add_argument("--operator-ready",action="store_true")
    p.add_argument("--span-evidence",type=Path)
    p.add_argument("--polarity",type=int,choices=(-1,1),default=1)
    a=p.parse_args()
    if not a.run:
        subprocess.run([sys.executable,str(ROOT/"src/pc/visible_visual_trial.py")],check=True)
        return
    if not a.operator_ready or a.span_evidence is None:
        p.error("--operator-ready and --span-evidence required after current physical confirmation")
    digest=hashlib.sha256(GUARD.read_bytes()).hexdigest()
    if digest!="1051e489ce396a0d24b937b8a3dd9aaeb9a60f4fab61e0a324df33925a87ecb6":
        raise RuntimeError("original eye guard changed since verification")
    log=ROOT/"build/external_vision.jsonl"
    deadline=time.monotonic()+20;row=None
    while time.monotonic()<deadline:
        try:
            candidate=latest(log)
            sid=candidate["vision"]["source_session_id"]
            visible_pulse(candidate,time.monotonic(),sid,a.polarity)
            if candidate["vision"]["target"] is not None:
                row=candidate;break
        except (OSError,ValueError,KeyError):pass
        time.sleep(.1)
    if row is None:
        print("NO_FRESH_FACE: no motion/configuration commands sent",flush=True)
        raise SystemExit(2)
    session={"operator_ready":True,"viewer_log":str(log),
             "camera_session":row["vision"]["source_session_id"],
             "span_evidence":str(a.span_evidence.resolve()),
             "span_evidence_sha256":hashlib.sha256(a.span_evidence.read_bytes()).hexdigest(),
             "guard_sha256":digest,"expires_epoch":time.time()+119,"polarity":a.polarity}
    path=ROOT/"build"/("visible_visual_"+str(time.time_ns())+".json")
    path.write_text(json.dumps(session,indent=2),encoding="utf-8")
    print("FRESH_FACE: START_10_SECONDS",row["vision"]["target"],flush=True)
    print("SESSION:",path,flush=True)
    subprocess.run([sys.executable,str(ROOT/"src/pc/visible_visual_trial.py"),"--run","--session",str(path)],check=True)
if __name__=="__main__":main()
