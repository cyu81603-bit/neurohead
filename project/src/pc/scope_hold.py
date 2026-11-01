"""F02 unloaded MG90S scope capture: 10s at 1500us, then disarm."""
import argparse,json,time
from pathlib import Path
from nh22 import Client,query,motion,stop
def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--run",action="store_true")
    p.add_argument("--out",type=Path)
    a=p.parse_args()
    if not a.run:
        print(json.dumps({"dry_run":True,"channel":1,"pulse_us":1500,"duration_s":10,"frames":500}))
        return
    client=Client(bind="192.168.10.10")
    result={"purpose":"unloaded_MG90S_oscilloscope_capture","requested_us":1500,
            "channel":1,"motion_commands_sent":0,"physical_waveform_verified":None}
    try:
        state=client.exchange(query())
        if state["status"] or state["active_mask"] or state["configured_mask"]!=2:
            raise RuntimeError("expected disarmed center-only F02 bench configuration")
        values=[0]*22;values[1]=1500
        began=time.perf_counter()
        for i in range(500):
            seq=client.next_sequence()
            state=client.exchange(motion(seq,2,values,int(time.monotonic()*1000)))
            result["motion_commands_sent"]+=1
            if state["sequence"]!=seq or state["status"]&2:raise RuntimeError("hold rejected")
            time.sleep(max(0,began+(i+1)*.02-time.perf_counter()))
    finally:
        try:result["final"]=client.exchange(stop(client.next_sequence()))
        finally:
            client.close()
            if a.out:a.out.write_text(json.dumps(result,indent=2),encoding="utf-8")
    print(json.dumps(result,indent=2))
if __name__=="__main__":main()
