import hashlib,json,subprocess,sys,time
from pathlib import Path
ROOT=Path(r"F:\NeuroHead\builds\nh22_20261028")
sys.path.insert(0,str(ROOT/"src/pc"))
from vision_bridge import latest
from loaded_visual_trial import visual_pulse
def read(p):return json.loads(p.read_text(encoding="utf-8-sig"))

def main():
    import argparse
    p=argparse.ArgumentParser(description='Legacy +/-5us diagnostic; default offline')
    p.add_argument('--run',action='store_true')
    p.add_argument('--operator-ready',action='store_true')
    a=p.parse_args()
    if not a.run:
        print(json.dumps({'dry_run':True,'limits_us':[1495,1505],'duration_s':10}))
        return
    if not a.operator_ready:p.error('--operator-ready requires current operator confirmation')
    pos=read(ROOT/"build/loaded_plus5_session.result.json")
    neg=read(ROOT/"build/loaded_minus5_session.result.json")
    if not pos.get("physical_observation") or not neg.get("physical_observation"):
        raise RuntimeError("missing physical observations")
    old=read(ROOT/"build/loaded_plus5_session.json")
    guard=Path(r"F:\NeuroHead\workspace\neurohead_fpga_2026\data\joint_setups\eye_horizontal.json")
    digest=hashlib.sha256(guard.read_bytes()).hexdigest()
    if digest!=old["guard_sha256"]:raise RuntimeError("eye record changed since physical verification")
    log=ROOT/"build/external_vision.jsonl"
    deadline=time.monotonic()+20;row=None
    while time.monotonic()<deadline:
        try:
            candidate=latest(log)
            sid=candidate["vision"]["source_session_id"]
            visual_pulse(candidate,time.monotonic(),sid)
            if candidate["vision"]["target"] is not None:row=candidate;break
        except (OSError,ValueError,KeyError):pass
        time.sleep(.1)
    if row is None:
        print("NO_FRESH_FACE: no motion/configuration commands sent",flush=True)
        raise SystemExit(2)
    session={"loaded_positive_observed":True,"loaded_negative_observed":True,
             "viewer_log":str(log),"camera_session":row["vision"]["source_session_id"],
             "guard_sha256":digest,"expires_epoch":time.time()+120,
             "operator_ready":True,
             "authority_basis":"current user authorization and loaded +/-5us observations"}
    path=ROOT/"build"/("external_visual_"+str(time.time_ns())+".json")
    path.write_text(json.dumps(session,indent=2),encoding="utf-8")
    print("FACE_PREFLIGHT_READY: START_10_SECONDS",row["vision"]["target"],flush=True)
    print("SESSION:",path,flush=True)
    subprocess.run([sys.executable,str(ROOT/"src/pc/loaded_visual_trial.py"),"--session",str(path)],check=True)
    
if __name__=="__main__":main()
