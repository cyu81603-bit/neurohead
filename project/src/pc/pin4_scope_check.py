"""Pin4 electrical-only scope pattern, with actuator signal disconnected."""
import argparse,hashlib,json,time
from pathlib import Path
from nh22 import Client,config,motion,query,stop
from eye_camera_feedback import acquire_run_lock
ROOT=Path(__file__).resolve().parents[2]
PHASES=((1000,3),(1500,3),(2000,3),(1500,1))
def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--run",action="store_true");p.add_argument("--signals-disconnected",action="store_true")
    p.add_argument("--show",action="store_true");a=p.parse_args()
    if not a.run:
        print(json.dumps({"dry_run":True,"channel":1,"pin":4,"points_and_seconds":PHASES,
                          "expected_period_ms":20,"actuator_must_be_disconnected":True}));return
    if not a.signals_disconnected:p.error("current disconnected-actuator confirmation required")
    window=None;closed=[False];label=None
    if a.show:
        import tkinter as tk
        window=tk.Tk();window.title("Pin4 示波器测试 · 舵机信号断开");window.geometry("570x220")
        tk.Label(window,text="直接测板上J10第4针 / 地第1针",font=("Microsoft YaHei UI",16)).pack(pady=16)
        label=tk.StringVar(value="准备输出");tk.Label(window,textvariable=label,font=("Microsoft YaHei UI",24,"bold")).pack(pady=10)
        tk.Button(window,text="停止输出",command=lambda:closed.__setitem__(0,True)).pack()
        window.protocol("WM_DELETE_WINDOW",lambda:closed.__setitem__(0,True));window.update()
    out=ROOT/"build"/("pin4_scope_"+str(time.time_ns())+".result.json")
    result={"purpose":"pin4_electrical_scope","physical_scope_observation":None,"samples":[]}
    try:
        with acquire_run_lock(ROOT/"build/eye_feedback.lock"):
            client=Client(bind="192.168.10.10")
            try:
                state=client.exchange(query())
                if state["status"] or state["active_mask"] or state["configured_mask"]&~3:
                    raise RuntimeError("disarmed eye-only setup required; no writes sent")
            except BaseException:client.close();raise
            try:
                seq=client.next_sequence();state=client.exchange(config(seq,1,1000,2000,1500,100,False))
                if state["sequence"]!=seq:raise RuntimeError("scope envelope rejected")
                began=time.perf_counter();count=0;endpoints=[]
                for phase,(pulse,seconds) in enumerate(PHASES):
                    print("SCOPE_PHASE",phase+1,"requested_us",pulse,flush=True)
                    for i in range(seconds*20):
                        if window is not None:
                            label.set(str(pulse)+" μs · 剩余 "+str(round(seconds-i*.05,1))+"秒");window.update()
                        if closed[0]:break
                        seq=client.next_sequence();pulses=[0]*22;pulses[1]=pulse
                        state=client.exchange(motion(seq,2,pulses,int(time.monotonic()*1000)))
                        if state["sequence"]!=seq or state["status"]&~5 or state["active_mask"]&~2:
                            raise RuntimeError("scope command rejected")
                        result["samples"].append({"requested_us":pulse,"pwm_setting_us":state["output_us"][1]})
                        count+=1;time.sleep(max(0,began+count*.05-time.perf_counter()))
                    if closed[0]:break
                    endpoints.append(state["output_us"][1])
                result["digital_endpoints_us"]=endpoints
                result["digital_checks_passed"]=not closed[0] and endpoints==[p for p,_ in PHASES]
                result["stopped_by_operator"]=closed[0]
            finally:
                try:
                    state=client.exchange(stop(client.next_sequence()))
                    if state["active_mask"] or state["status"]:raise RuntimeError("scope stop not acknowledged")
                    seq=client.next_sequence();state=client.exchange(config(seq,1,1500,1500,1500,1,False))
                    if state["sequence"]!=seq:raise RuntimeError("scope center-only restore failed")
                    result["final"]=state
                finally:client.close();out.write_text(json.dumps(result,indent=2),encoding="utf-8")
    finally:
        if window is not None:window.destroy()
    print("RESULT",out,flush=True)
    print(json.dumps({k:v for k,v in result.items() if k!="samples"},indent=2))
if __name__=="__main__":main()
