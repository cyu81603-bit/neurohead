"""Upload center-only settings for eye channels; never enables PWM."""
import argparse,json
from pathlib import Path
from nh22 import Client,config,query
ROOT=Path(__file__).resolve().parents[2]
def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument("--execute",action="store_true");a=p.parse_args()
    if not a.execute:
        print(json.dumps({"dry_run":True,"channels":[0,1],"limits_us":[1500,1500],"motion_commands_sent":0}));return
    client=Client(bind="192.168.10.10")
    try:
        state=client.exchange(query())
        if state["status"] or state["active_mask"] or state["configured_mask"]&~3:
            raise RuntimeError("disarmed eye-only board required")
        for channel in (0,1):
            seq=client.next_sequence();state=client.exchange(config(seq,channel,1500,1500,1500,1,False))
            if state["sequence"]!=seq or state["active_mask"]:raise RuntimeError("center-only config rejected")
        if state["configured_mask"]!=3:raise RuntimeError("eye configuration incomplete")
        result={"motion_commands_sent":0,"final":state}
        (ROOT/"build/eyes_center_only_config.json").write_text(json.dumps(result,indent=2),encoding="utf-8")
        print(json.dumps(result,indent=2))
    finally:client.close()
if __name__=="__main__":main()
