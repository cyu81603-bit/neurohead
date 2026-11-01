"""Read-only NQ v2 probe; never sends configuration or movement packets."""
import argparse,json,time,socket
from pathlib import Path
from nh22 import Client,query
def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--host",default="192.168.10.20")
    p.add_argument("--bind",default="192.168.10.10")
    p.add_argument("--count",type=int,default=20)
    p.add_argument("--out",type=Path)
    p.add_argument("--expect-disabled",action="store_true")
    a=p.parse_args()
    if not 1<=a.count<=100:p.error("count must be 1..100")
    client=None
    for attempt in range(3):
        try:client=Client(a.host,bind=a.bind,timeout=2);break
        except socket.timeout:
            if attempt==2:raise
    rows=[]
    try:
        for i in range(a.count):
            started=time.monotonic();stamp=int(started*1000)&0xffffffff
            rtt_started=time.perf_counter()
            state=client.exchange(query(i,stamp))
            if not state["query"] or state["echo_ms"]!=stamp:raise RuntimeError("query echo mismatch")
            if a.expect_disabled and (state["active_mask"] or state["configured_mask"] or state["status"]):
                raise RuntimeError("board is not in the expected unconfigured/disarmed state")
            rows.append({"rtt_ms":(time.perf_counter()-rtt_started)*1000,"telemetry":state})
            time.sleep(.05)
    finally:client.close()
    result={"read_only":True,"motion_commands_sent":0,"configuration_commands_sent":0,
            "successful_queries":len(rows),"last":rows[-1]["telemetry"],
            "rtt_ms_min":min(r["rtt_ms"] for r in rows),"rtt_ms_max":max(r["rtt_ms"] for r in rows),
            "samples":rows}
    if a.out:a.out.write_text(json.dumps(result,indent=2),encoding="utf-8")
    print(json.dumps({k:v for k,v in result.items() if k!="samples"},indent=2))
if __name__=="__main__":main()
