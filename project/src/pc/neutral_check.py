"""Two-second loaded neutral verification, Pin10 only; no target variation."""
import argparse,hashlib,json,time
from pathlib import Path
from nh22 import Client,query,motion,stop
def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--run",action="store_true");p.add_argument("--operator-ready",action="store_true")
    p.add_argument("--out",type=Path);a=p.parse_args()
    if not a.run:print('{"dry_run":true,"channel":0,"pulse_us":1500,"seconds":2}');return
    if not a.operator_ready:p.error("current operator confirmation required")
    guard=Path(r"F:\NeuroHead\workspace\neurohead_fpga_2026\data\joint_setups\eye_horizontal.json")
    before=hashlib.sha256(guard.read_bytes()).hexdigest()
    result={"purpose":"loaded_eye_static_neutral","pulse_us":1500,"seconds":2,"physical_observation":None}
    client=Client(bind="192.168.10.10");values=[0]*22;values[0]=1500;count=0
    try:
        state=client.exchange(query())
        if state["status"] or state["active_mask"] or state["configured_mask"]!=1:
            raise RuntimeError("expected disarmed Pin10-only bench state")
        began=time.perf_counter()
        for i in range(100):
            seq=client.next_sequence()
            state=client.exchange(motion(seq,1,values,int(time.monotonic()*1000)))
            if state["sequence"]!=seq or state["status"]&2:raise RuntimeError("neutral request rejected")
            count+=1;time.sleep(max(0,began+(i+1)*.02-time.perf_counter()))
    finally:
        try:result["final"]=client.exchange(stop(client.next_sequence()))
        finally:
            client.close();result["commands_sent"]=count
            result["original_eye_guard_unchanged"]=hashlib.sha256(guard.read_bytes()).hexdigest()==before
            if a.out:a.out.write_text(json.dumps(result,indent=2),encoding="utf-8")
    print(json.dumps(result,indent=2))
if __name__=="__main__":main()
