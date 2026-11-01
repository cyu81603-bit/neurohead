"""Known-good Pin10 comparison for the pitch servo; bounded mechanical diagnostic."""
import argparse,hashlib,json,time
from pathlib import Path
from nh22 import Client,config,motion,query,stop
from eye_camera_feedback import acquire_run_lock
ROOT=Path(__file__).resolve().parents[2]
POINTS=(1500,1450,1500,1550,1500)
def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--run",action="store_true");p.add_argument("--operator-ready",action="store_true")
    a=p.parse_args()
    if not a.run:
        print(json.dumps({"dry_run":True,"signal_pin":10,"channel":0,"servo":"temporarily connected pitch MG90S",
                          "points_us":POINTS,"seconds":7.5,"step_us_per_frame":2}));return
    if not a.operator_ready:p.error("current temporary wiring confirmation required")
    marker=json.loads((ROOT/"build/diagnostic_wiring.json").read_text(encoding="utf-8-sig"))
    if marker.get("state")!="vertical_on_pin10_operator_confirmed":
        raise ValueError("confirmed diagnostic wiring required")
    guard=Path(r"F:\NeuroHead\workspace\neurohead_fpga_2026\data\joint_setups\eye_horizontal.json")
    digest=hashlib.sha256(guard.read_bytes()).hexdigest()
    if digest!="1051e489ce396a0d24b937b8a3dd9aaeb9a60f4fab61e0a324df33925a87ecb6":
        raise ValueError("original guard changed")
    result={"purpose":"pitch_servo_on_known_pin10","points_us":POINTS,"physical_observation":None}
    out=ROOT/"build"/("pitch_on_pin10_"+str(time.time_ns())+".result.json")
    with acquire_run_lock(ROOT/"build/eye_feedback.lock"):
        client=Client(bind="192.168.10.10");samples=[]
        try:
            state=client.exchange(query())
            if state["status"] or state["active_mask"] or state["configured_mask"]!=3:
                raise RuntimeError("disarmed eye-only board required; no writes sent")
        except BaseException:client.close();raise
        try:
            seq=client.next_sequence();state=client.exchange(config(seq,0,1450,1550,1500,2,False))
            if state["sequence"]!=seq:raise RuntimeError("comparison envelope rejected")
            began=time.perf_counter()
            for i in range(150):
                if hashlib.sha256(guard.read_bytes()).hexdigest()!=digest:raise RuntimeError("original guard changed")
                value=POINTS[i//30];values=[value]+[0]*21;seq=client.next_sequence()
                state=client.exchange(motion(seq,1,values,int(time.monotonic()*1000)))
                if state["sequence"]!=seq or state["status"]&~5 or state["active_mask"]&~1:
                    raise RuntimeError("comparison command rejected")
                samples.append({"requested_us":value,"pwm_setting_us":state["output_us"][0]})
                time.sleep(max(0,began+(i+1)*.05-time.perf_counter()))
            result["digital_endpoints_us"]=[samples[i]["pwm_setting_us"] for i in (29,59,89,119,149)]
            if result["digital_endpoints_us"]!=list(POINTS):raise RuntimeError("comparison endpoints not reached")
            result["digital_checks_passed"]=True
        finally:
            try:
                state=client.exchange(stop(client.next_sequence()))
                if state["active_mask"] or state["status"]:raise RuntimeError("comparison stop not acknowledged")
                seq=client.next_sequence();state=client.exchange(config(seq,0,1500,1500,1500,1,False))
                if state["sequence"]!=seq:raise RuntimeError("comparison center-only restore failed")
                result["final"]=state
            finally:
                client.close();result["motion_frames"]=len(samples);result["samples"]=samples
                result["original_guard_unchanged"]=hashlib.sha256(guard.read_bytes()).hexdigest()==digest
                out.write_text(json.dumps(result,indent=2),encoding="utf-8")
    print("RESULT",out);print(json.dumps({k:v for k,v in result.items() if k!="samples"},indent=2))
if __name__=="__main__":main()
