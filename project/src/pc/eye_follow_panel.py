from shared_hardware import SHARED_VISION_LOG,SHARED_VISION_STOP
"""Continuous eye-follow panel. Opening it sends no robot movement."""
import argparse,hashlib,json,re,subprocess,sys,time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
from vision_bridge import latest
from eye_vertical_settings import vertical_settings
HIDDEN=getattr(subprocess,"CREATE_NO_WINDOW",0)
def verified_command(axis="both",reverse=False,reference_start=False):
    marker=ROOT/"build/diagnostic_wiring.json"
    if marker.exists() and json.loads(marker.read_text(encoding="utf-8-sig")).get("active"):
        raise ValueError("临时对照接线中：恢复左右Pin10、上下Pin4后才能启动正常跟随")
    profile=json.loads((ROOT/"config/eye_follow.json").read_text(encoding="utf-8-sig"))
    if profile.get("status")!="operator_verified_basic_horizontal_follow":raise ValueError("No accepted horizontal profile")
    expected={"duration_s":20,"limits_us":[1100,1900],"max_rate_us_per_s":200,
              "gain":.8,"provisional_image_dx_per_us":.002}
    if profile.get("parameters")!=expected:raise ValueError("Controller parameters differ from accepted trial")
    for name,digest in profile["verified_files"].items():
        path=(ROOT/name).resolve()
        if ROOT.resolve() not in path.parents:raise ValueError("Profile file outside project")
        if hashlib.sha256(path.read_bytes()).hexdigest()!=digest:raise ValueError("Changed file: "+name)
    proof=json.loads((ROOT/profile["accepted_result"]).read_text(encoding="utf-8-sig"))
    if not (proof.get("digital_checks_passed") and proof.get("operator_horizontal_face_follow_confirmed")
            and proof.get("operator_return_confirmed") and proof.get("original_eye_guard_unchanged")):
        raise ValueError("Missing real-world follow observation")
    if axis not in ("horizontal","vertical","both"):raise ValueError("unknown eye axis")
    if axis!="horizontal":
        vertical=json.loads((ROOT/"config/eye_vertical.json").read_text(encoding="utf-8-sig"))
        if not vertical.get("assembled_at_1500_operator_confirmed") or not vertical.get("initial_tracking_requested_by_operator"):
            raise ValueError("vertical setup/request missing")
        if axis=="both" and not (vertical.get("basic_vertical_follow_operator_verified")
                                 or vertical.get("simultaneous_tracking_requested_by_operator")):
            raise ValueError("first verify vertical-only feedback")
    command=[sys.executable,str(ROOT/"src/pc/eye_camera_feedback.py"),"pilot","--run","--operator-ready","--continuous",
             "--span-evidence",str(ROOT/profile["span_evidence"]),"--direction-evidence",str(ROOT/profile["direction_evidence"]),
             "--axis",axis,"--vertical-profile",str(ROOT/"config/eye_vertical.json")]
    if reverse and axis!="horizontal":command.append("--vertical-reverse")
    if reference_start and axis!="horizontal":command.append("--vertical-reference-start")
    return command
class Panel:
    def __init__(self,window):
        import tkinter as tk
        self.window=window;self.child=None;self.camera=None;self.output=None;self.stop_requested=False
        self.stop_file=ROOT/"build/eye_follow_panel.stop"
        self.heartbeat_file=ROOT/"build/eye_follow_panel.heartbeat"
        self.status_file=ROOT/"build/eye_follow_runtime.json"
        self.run_log=None;self.camera_starting=False;self.closing=False
        window.title("NeuroHead 双轴跟随 r8上下行程微调版 · 上下1000–2000μs")
        window.geometry("790x490");window.resizable(False,False)
        tk.Label(window,text="眼睛持续人脸跟随 · r8上下行程微调版",font=("Microsoft YaHei UI",20,"bold")).pack(pady=(20,10))
        tk.Label(window,text="双轴请接好左右Pin10、上下Pin4及两只外部5V供电，再点击开始。",font=("Microsoft YaHei UI",11)).pack()
        tk.Label(window,text="双轴同时对准画面中心并持续运行；上下行程在已通过的范围基础上，两端各增加100μs。",font=("Microsoft YaHei UI",11)).pack(pady=5)
        try:preferences=json.loads((ROOT/"build/eye_follow_preferences.json").read_text(encoding="utf-8"))
        except (OSError,ValueError):preferences={}
        chosen=preferences.get("axis","both")
        self.axis=tk.StringVar(value=chosen if chosen in ("vertical","horizontal","both") else "both")
        self.reverse=tk.BooleanVar(value=bool(preferences.get("vertical_reverse",False)))
        choose=tk.Frame(window);choose.pack(pady=8)
        self.axis_controls=[]
        for label,value in (("上下 · Pin4","vertical"),("左右 · Pin10","horizontal"),("左右＋上下","both")):
            button=tk.Radiobutton(choose,text=label,variable=self.axis,value=value)
            button.pack(side="left",padx=8)

            self.axis_controls.append(button)
        reverse=tk.Checkbutton(window,text="上下反向（先停止再修改）",variable=self.reverse)
        reverse.pack();self.axis_controls.append(reverse)
        vp=json.loads((ROOT/"config/eye_vertical.json").read_text(encoding="utf-8-sig"))
        lo,hi,rate=vertical_settings(vp)
        tk.Label(window,text=f"上下范围{lo}–{hi}μs，低速{rate}μs/s；左右保留已通过的参数。",
                 font=("Microsoft YaHei UI",10)).pack(pady=4)
        tk.Label(window,text="上下使用10μs有效步进，小变化累积后输出；上下行程两端各增加100μs，方向和左右参数保留。",
                 font=("Microsoft YaHei UI",10)).pack(pady=2)
        self.vision=tk.StringVar(value="正在检查USB Cam画面…");self.status=tk.StringVar(value="尚未发送运动指令")
        tk.Label(window,textvariable=self.vision,font=("Microsoft YaHei UI",11)).pack(pady=8)
        tk.Label(window,textvariable=self.status,font=("Microsoft YaHei UI",11),wraplength=670).pack(pady=8)
        row=tk.Frame(window);row.pack(pady=12)
        tk.Button(row,text="打开相机预览",width=16,command=self.open_camera).pack(side="left",padx=8)
        self.start=tk.Button(row,text="开始持续跟随",width=16,command=self.begin);self.start.pack(side="left",padx=8)
        self.stop=tk.Button(row,text="停止",width=12,command=self.request_stop,state="disabled");self.stop.pack(side="left",padx=8)
        window.protocol("WM_DELETE_WINDOW",self.close);window.after(300,self.poll)
    def camera_fresh(self):
        try:
            row=latest(SHARED_VISION_LOG)
            return 0<=time.monotonic()-row["host_monotonic_s"]<.75,row
        except (OSError,ValueError,KeyError):return False,None
    def launch_camera(self):
        if self.closing:return
        (SHARED_VISION_STOP).unlink(missing_ok=True)
        handle=(ROOT/"build/panel_camera.log").open("wb")
        self.camera=subprocess.Popen([sys.executable,str(ROOT/"src/pc/external_vision_source.py"),
            "--show","--duration","0"],cwd=str(ROOT),stdout=handle,stderr=subprocess.STDOUT,creationflags=HIDDEN)
        handle.close();(ROOT/"build/external_vision.pid").write_text(str(self.camera.pid),encoding="utf-8")
        self.camera_starting=False;self.status.set("USB Cam已打开，请让脸进入画面")
    def open_camera(self):
        fresh,row=self.camera_fresh()
        if fresh and row.get("stream_duration_s")==0:
            self.status.set("USB Cam预览已在持续运行");return
        if self.camera_starting:return
        if self.camera is not None and self.camera.poll() is None:
            self.status.set("正在等待USB Cam启动");return
        self.camera_starting=True
        if fresh:
            # Existing finite preview cooperatively releases the named device.
            (SHARED_VISION_STOP).write_text("upgrade preview",encoding="utf-8")
            self.window.after(1200,self.launch_camera)
        else:self.launch_camera()
    def begin(self,continuous=True):
        if self.child is not None:return
        try:
            command=verified_command(self.axis.get(),self.reverse.get(),False)
            if not continuous:command.remove("--continuous")
            (ROOT/"build/eye_follow_preferences.json").write_text(json.dumps(
                {"axis":self.axis.get(),"vertical_reverse":self.reverse.get()}),encoding="utf-8")
            self.open_camera();self.stop_file.unlink(missing_ok=True)
            self.heartbeat_file.write_text("panel alive",encoding="utf-8")
            self.run_log=ROOT/"build"/("panel_follow_"+str(time.time_ns())+".log")
            self.output=self.run_log.open("wb")
            command+=["--stop-file",str(self.stop_file),"--heartbeat-file",str(self.heartbeat_file),"--status-file",str(self.status_file)]
            self.child=subprocess.Popen(command,cwd=str(ROOT),stdout=self.output,stderr=subprocess.STDOUT,creationflags=HIDDEN)
            self.stop_requested=False;self.start.configure(state="disabled");self.stop.configure(state="normal")
            self.saved_control_states=[control.cget("state") for control in self.axis_controls]
            for control in self.axis_controls:control.configure(state="disabled")
            self.status.set("等待USB Cam实时画面；无脸时回中等待" if continuous else "等待人脸，随后开始20秒试运行")
        except Exception as exc:
            if self.output:self.output.close();self.output=None
            self.status.set("未开始："+str(exc))
    def request_stop(self):
        if self.child is not None:
            self.stop_requested=True;self.stop_file.write_text("operator stop",encoding="utf-8")
            self.status.set("正在停止，等待板卡确认")
    def stopped_state(self,text):
        match=re.search(r"RESULT (.+)",text)
        if not match:return False
        try:
            result=json.loads(Path(match.group(1).strip()).read_text(encoding="utf-8-sig"))
            return result.get("final",{}).get("active_mask")==0 and result.get("final",{}).get("status")==0
        except (OSError,ValueError):return False
    def poll(self):
        fresh,row=self.camera_fresh()
        self.vision.set("USB Cam：画面正常 | "+("已检测到人脸" if row["vision"].get("target") is not None else "未检测到人脸") if fresh else "USB Cam：画面未更新")
        if self.child is not None:
            self.heartbeat_file.touch()
            code=self.child.poll()
            if code is None and not self.stop_requested:
                try:
                    status=json.loads(self.status_file.read_text(encoding="utf-8"))
                    if status.get("running") and time.time()-status["updated_epoch"]<2:
                        seconds=int(status["elapsed_s"])
                        if status.get("reference_pending"):state="正在建立上下参考，请保持人脸位置"
                        elif status.get("returning_to_neutral"):state="试运行即将结束，正在回中"
                        elif not status["face_present"]:state="未见人脸，缓慢回中"
                        elif status.get("vertical_limited"):state="上下PWM到"+str(status.get("outputs_by_channel",{}).get("1","?"))+"μs限幅，尚未对准"
                        elif status.get("horizontal_limited"):state="左右已到行程限幅"
                        else:state="跟随中"
                        axis_label={"vertical":"上下","horizontal":"左右","both":"双轴"}[self.axis.get()]
                        self.status.set(axis_label+("持续跟随" if status.get("continuous") else "20秒试运行")+" %02d:%02d · %s"%(seconds//60,seconds%60,state))
                except (OSError,ValueError,KeyError):pass
            if code is not None:
                self.output.close();self.output=None
                text=self.run_log.read_text(encoding="utf-8",errors="replace")
                if "START " not in text:
                    self.status.set("启动已取消，未发送运动" if self.stop_requested else "未开始："+text.strip().splitlines()[-1])
                elif self.stopped_state(text):
                    self.status.set("已停止PWM" if self.stop_requested else "运行结束，PWM已停止；"+("" if code==0 else text.strip().splitlines()[-1]))
                else:self.status.set("无法确认板卡停止，请查看本轮日志")
                self.child=None;self.start.configure(state="normal");self.stop.configure(state="disabled")
                for control,state in zip(self.axis_controls,self.saved_control_states):control.configure(state=state)
                if self.closing:self.window.destroy();return
        if not self.closing or self.child is not None:self.window.after(300,self.poll)
    def close(self):
        if self.child is None:self.closing=True;self.window.destroy()
        else:self.closing=True;self.request_stop()
def main():
    import tkinter as tk
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--self-test",action="store_true")
    p.add_argument("--autostart-trial",action="store_true",help="visible finite 20s trial after normal wiring confirmation")
    a=p.parse_args()
    window=tk.Tk()
    if a.self_test:window.withdraw()
    panel=Panel(window)
    if a.self_test:
        window.update_idletasks();assert panel.child is None
        assert panel.start.cget("state")=="normal" and panel.stop.cget("state")=="disabled"
        assert "--continuous" in verified_command()
        window.destroy();print("PANEL_SMOKE_PASS: idle continuous interface, no robot process")
    else:
        if a.autostart_trial:window.after(1000,lambda:panel.begin(continuous=False))
        window.mainloop()
if __name__=="__main__":main()
