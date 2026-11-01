from shared_hardware import SHARED_VISION_LOG,SHARED_VISION_STOP
"""Eye-mounted USB Cam: bounded calibration, finite trials or continuous follow.
Default offline; operator readiness, original guard and observed span still apply.
"""
import argparse,hashlib,json,math,sys,time
from collections import deque
from pathlib import Path
from nh22 import Client,config,motion,query,stop
from visible_visual_trial import ROOT,GUARD,validate_evidence
from loaded_visual_trial import visual_pulse
from vision_bridge import latest
from image_feedback import Feedback,estimate_jacobian
from runtime_logs import JsonlLog,write_status
from eye_reference import StartupVerticalReference
from eye_vertical_settings import vertical_settings,vertical_output_settings
from effective_pulse import EffectivePulseOutput
class OperatorStop(RuntimeError):pass
def acquire_run_lock(path):
    import msvcrt
    if path.resolve()==(ROOT/'build/eye_feedback.lock').resolve():
        path=Path(r'F:\NeuroHead\builds\nh21_20261024\build\eye_feedback.lock')
    handle=path.open("a+b");handle.seek(0,2)
    if handle.tell()==0:handle.write(b"0");handle.flush()
    handle.seek(0)
    try:msvcrt.locking(handle.fileno(),msvcrt.LK_NBLCK,1)
    except OSError:
        handle.close();raise RuntimeError("another eye feedback run is already active")
    return handle
def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("stage",choices=("calibrate","track","pilot"))
    p.add_argument("--axis",choices=("horizontal","vertical","both"),default="horizontal")
    p.add_argument("--vertical-reverse",action="store_true")
    p.add_argument("--vertical-reference-start",action="store_true")
    p.add_argument("--vertical-profile",type=Path,default=ROOT/"config/eye_vertical.json")
    for name in ("run","operator-ready","continuous"):p.add_argument("--"+name,action="store_true")
    for name in ("span-evidence","calibration","direction-evidence","stop-file","heartbeat-file","status-file"):
        p.add_argument("--"+name,type=Path)
    a=p.parse_args()
    if a.axis!="horizontal" and a.stage!="pilot":p.error("new vertical feedback uses pilot mode")
    if a.continuous and a.stage=="calibrate":p.error("calibration is always finite")
    if not a.run:
        preview_limits=list(vertical_settings(json.loads(a.vertical_profile.read_text(encoding="utf-8-sig")))[:2]) if a.axis!="horizontal" else [1100,1900]
        print(json.dumps({"dry_run":True,"stage":a.stage,"continuous":a.continuous,
                          "duration_s":None if a.continuous else 12 if a.stage=="calibrate" else 20,
                          "axis":a.axis,"channels":[0] if a.axis=="horizontal" else [1] if a.axis=="vertical" else [0,1],
                          "camera":"USB Cam","limits_us":preview_limits if a.axis=="vertical" else [1100,1900]}));return
    if not a.operator_ready or a.span_evidence is None:
        p.error("current operator readiness and --span-evidence required")
    if a.continuous and a.stop_file is None:p.error("continuous mode requires --stop-file")
    digest=hashlib.sha256(GUARD.read_bytes()).hexdigest()
    if digest!="1051e489ce396a0d24b937b8a3dd9aaeb9a60f4fab61e0a324df33925a87ecb6":
        raise ValueError("original guard changed")
    span={"span_evidence":str(a.span_evidence),"span_evidence_sha256":hashlib.sha256(a.span_evidence.read_bytes()).hexdigest()}
    validate_evidence(span)
    calibration=None;direction=None
    if a.stage=="track":
        if a.calibration is None:p.error("--calibration required")
        calibration=json.loads(a.calibration.read_text(encoding="utf-8-sig"))
        if (calibration.get("purpose")!="eye_camera_calibration" or not calibration.get("digital_checks_passed")
            or not calibration.get("calibration_valid") or not calibration.get("original_eye_guard_unchanged")):
            raise ValueError("valid physical image calibration required")
        controller=Feedback(calibration["image_calibration"]["image_dx_per_us"])
    if a.stage=="pilot":
        if a.direction_evidence is None:p.error("--direction-evidence required")
        direction=json.loads(a.direction_evidence.read_text(encoding="utf-8-sig"))
        if direction.get("status")!="provisional_direction_not_full_calibration":raise ValueError("incorrect direction evidence")
        for item in direction["source_results"]:
            if hashlib.sha256(Path(item["path"]).read_bytes()).hexdigest()!=item["sha256"]:
                raise ValueError("direction source evidence changed")
        controller=Feedback(direction["provisional_image_dx_per_us"],gain=.8,max_rate=200)
    channels=[0] if a.axis=="horizontal" else [1] if a.axis=="vertical" else [0,1]
    mask=sum(1<<channel for channel in channels)
    vertical_controller=None
    if 1 in channels:
        vertical_profile=json.loads(a.vertical_profile.read_text(encoding="utf-8-sig"))
        if (vertical_profile.get("channel")!=1 or not vertical_profile.get("assembled_at_1500_operator_confirmed")
            or not vertical_profile.get("initial_tracking_requested_by_operator")):
            raise ValueError("vertical assembly and explicit initial tracking request required")
        if a.axis=="both" and not (vertical_profile.get("basic_vertical_follow_operator_verified")
                                   or vertical_profile.get("simultaneous_tracking_requested_by_operator")):
            raise ValueError("verify vertical-only feedback before combining axes")
        vertical_lo,vertical_hi,vertical_rate=vertical_settings(vertical_profile)
        vertical_controller=Feedback(-.002 if a.vertical_reverse else .002,gain=.8,max_rate=vertical_rate,
                                     lo=vertical_lo,hi=vertical_hi,neutral=1500)
        vertical_quantum,vertical_output_slew=vertical_output_settings(vertical_profile)
        vertical_output=EffectivePulseOutput(vertical_lo,vertical_hi,quantum_us=vertical_quantum,
                                             max_rate_us_per_s=vertical_rate)
    reference_capture=StartupVerticalReference() if a.vertical_reference_start and 1 in channels else None
    vertical_reference=0. if reference_capture is None else None
    with acquire_run_lock(ROOT/"build/eye_feedback.lock"):
        def check():
            if a.stop_file is not None and a.stop_file.exists():raise OperatorStop("operator stop requested")
            if a.heartbeat_file is not None:
                if not a.heartbeat_file.exists() or not -1<=time.time()-a.heartbeat_file.stat().st_mtime<=2:
                    raise RuntimeError("control panel heartbeat lost")
            if hashlib.sha256(GUARD.read_bytes()).hexdigest()!=digest:raise RuntimeError("original guard changed")
        log=SHARED_VISION_LOG;row=None
        preflight_deadline=time.monotonic()+20
        print("WAITING_FOR_FRESH_FACE: no configuration or motion sent",flush=True)
        while time.monotonic()<preflight_deadline:
            check()
            try:
                candidate=latest(log);sid=candidate["vision"]["source_session_id"]
                visual_pulse(candidate,time.monotonic(),sid)
                if (a.continuous and candidate.get("stream_duration_s")==0) or (not a.continuous and candidate["vision"]["target"] is not None):
                    row=candidate;break
            except (OSError,ValueError,KeyError):pass
            time.sleep(.1)
        if row is None:raise ValueError("no fresh face in eligible camera stream; no configuration or motion sent")
        result={"purpose":"eye_camera_"+("calibration" if a.stage=="calibrate" else "feedback"),
                "camera":"USB Cam","camera_mount":"moves_with_eyeball_operator_confirmed",
                "continuous":a.continuous,"axis":a.axis,"channel_mask":mask,
                "vertical_active_limits_us":[vertical_lo,vertical_hi] if 1 in channels else None,
                "vertical_direction_is_provisional":1 in channels,
                "vertical_reverse":a.vertical_reverse,"physical_observation":None,**span}
        if direction is not None:
            result.update(direction_evidence=str(a.direction_evidence),scale_is_provisional=True,max_rate_us_per_s=200)
        if calibration is not None:
            result.update(calibration_path=str(a.calibration),calibration_sha256=hashlib.sha256(a.calibration.read_bytes()).hexdigest())
        if a.stage!="calibrate":
            active_controllers={ch:(controller if ch==0 else vertical_controller) for ch in channels}
            result["feedback_settings"]={str(ch):{"limits_us":[c.lo,c.hi],"gain":c.gain,
                "max_rate_us_per_s":c.max_rate,"provisional_image_d_per_us":c.jacobian}
                for ch,c in active_controllers.items()}
            result["max_rate_us_per_s"]=active_controllers[channels[0]].max_rate
        if 1 in channels:
            result["vertical_output"]={"quantum_us":vertical_quantum,"hardware_slew_us_per_frame":vertical_output_slew,
                "hypothesis":"align useful pulse changes with known unloaded output; servo deadband unmeasured"}
        if a.axis=="vertical":
            result.pop("direction_evidence",None)
            result["vertical_direction_source"]="provisional_operator_selectable"
        out=ROOT/"build"/("eye_"+a.stage+"_"+str(time.time_ns())+".result.json")
        print("START",a.stage,"RESULT",out,flush=True)
        client=Client(bind="192.168.10.10")
        # A pre-existing controller owns any active/held neck. Never stop it
        # while refusing this new run. Configured but idle neck slots are OK.
        try:
            state=client.exchange(query())
            if (state["status"] or state["active_mask"] or state["configured_mask"]&mask!=mask
                    or state["configured_mask"]&~(3|(7<<18))):
                raise ValueError("board must be disarmed with eye channel configured; no actuator writes sent")
        except BaseException:
            client.close()
            raise
        samples=deque(maxlen=1200) if a.continuous else []
        stream=JsonlLog(out.with_suffix(".samples.jsonl")) if a.continuous else None
        i=0;started=time.perf_counter();began=started
        try:
            for channel in channels:
                seq=client.next_sequence()
                lo,hi,step=(vertical_lo,vertical_hi,vertical_output_slew) if channel==1 else ((1400,1600,10) if a.stage=="calibrate" else (1100,1900,10))
                state=client.exchange(config(seq,channel,lo,hi,1500,step,False))
                if state["sequence"]!=seq:raise RuntimeError("configuration rejected")
            total=240 if a.stage=="calibrate" else 400
            return_start=total-max(20,math.ceil((max(1500-vertical_lo,vertical_hi-1500)/min(vertical_rate,50)+.6)/.05)) if 1 in channels else 380
            while a.continuous or i<total:
                check()
                if not a.continuous and time.perf_counter()-started>30:raise RuntimeError("trial expired")
                row=latest(log);visual_pulse(row,time.monotonic(),sid)
                v=row["vision"];x=v["target"][0] if v["target"] is not None else None
                y=v["target"][1] if v["target"] is not None else None
                phase=i//48 if a.stage=="calibrate" else None
                if reference_capture is not None and vertical_reference is None:
                    vertical_reference=reference_capture.observe(v["frame_id"],v["frame_time"],y)
                reference_pending=vertical_reference is None
                vertical_error=None if y is None else max(-1,min(1,y-(vertical_reference or 0.)))
                values=[0]*22
                desired_pitch=1500 if 1 in channels else None
                if reference_pending:
                    for channel in channels:values[channel]=1500
                else:
                    if 0 in channels:
                        if phase is not None:values[0]=(1500,1600,1500,1400,1500)[phase]
                        else:values[0]=controller.update(v["frame_id"],v["frame_time"],x) if a.continuous or i<return_start else 1500
                    if 1 in channels:
                        desired_pitch=vertical_controller.update(v["frame_id"],v["frame_time"],vertical_error) if a.continuous or i<return_start else 1500
                        values[1]=vertical_output.update(desired_pitch,v["frame_id"],v["frame_time"])
                value=values[channels[0]]
                seq=client.next_sequence()
                state=client.exchange(motion(seq,mask,values,int(time.monotonic()*1000)))
                if state["sequence"]!=seq or state["status"]&~5 or state["active_mask"]&~mask:
                    raise RuntimeError("unexpected sequence, fault or active channel")
                sample={"phase":phase,"phase_elapsed_s":(i%48)*.05 if phase is not None else None,
                        "settled_window":i%48>=36 if phase is not None else False,"requested_us":value,
                        "output_us":state["output_us"][channels[0]],"source_frame":v["frame_id"],
                        "requested_by_channel":{str(ch):values[ch] for ch in channels},
                        "output_by_channel":{str(ch):state["output_us"][ch] for ch in channels},
                        "face_y":y,"vertical_error":vertical_error,"reference_pending":reference_pending,
                        "desired_pitch_us":desired_pitch,
                        "vertical_reference_y":vertical_reference,
                        "frame_time":v["frame_time"],"face_x":x,
                        "saturated":((controller.saturated if 0 in channels else False) or
                                     (vertical_controller.saturated if 1 in channels else False))
                                     if phase is None and (a.continuous or i<return_start) else False}
                samples.append(sample);i+=1
                if stream:stream.write_row(sample)
                if a.status_file is not None and i%5==0:
                    write_status(a.status_file,{"running":True,"updated_epoch":time.time(),"continuous":a.continuous,
                        "elapsed_s":time.perf_counter()-started,"motion_frames":i,"face_present":x is not None,
                        "requested_us":value,"output_us":state["output_us"][channels[0]],"axis":a.axis,
                        "reference_pending":reference_pending,"vertical_reference_y":vertical_reference,
                        "horizontal_limited":controller.saturated if 0 in channels else False,
                         "vertical_limited":vertical_controller.saturated and values[1] in (vertical_lo,vertical_hi) if 1 in channels else False,
                        "pitch_desired_us":desired_pitch,"pitch_command_us":values[1] if 1 in channels else None,
                        "returning_to_neutral":not a.continuous and i-1>=return_start,
                        "face_error_x":x,"face_error_y":vertical_error,
                        "outputs_by_channel":{str(ch):state["output_us"][ch] for ch in channels}})
                # Pace from the current loop, preventing burst catch-up after long delays.
                next_tick=began+i*.05
                if time.perf_counter()>next_tick+.1:began=time.perf_counter()-i*.05;next_tick=began+i*.05
                time.sleep(max(0,next_tick-time.perf_counter()))
            if any(samples[-1]["output_by_channel"][str(ch)]!=1500 for ch in channels):
                raise RuntimeError("neutral setting not reached on every selected eye axis")
            result["digital_checks_passed"]=True
            if a.stage=="calibrate":
                try:result["image_calibration"]=estimate_jacobian(samples);result["calibration_valid"]=True
                except ValueError as exc:result["calibration_valid"]=False;result["calibration_error"]=str(exc)
        except BaseException as exc:
            result["interruption_reason"]=str(exc)
            if a.continuous and isinstance(exc,OperatorStop):
                result["stopped_by_operator"]=True;result["digital_checks_passed"]=True
            else:raise
        finally:
            try:
                state=client.exchange(stop(client.next_sequence()))
                if state["active_mask"] or state["status"]:raise RuntimeError("stop not acknowledged")
                for channel in channels:
                    seq=client.next_sequence();state=client.exchange(config(seq,channel,1500,1500,1500,1,False))
                    if state["sequence"]!=seq or state["active_mask"]:raise RuntimeError("center-only restore rejected")
                result["final"]=state
            finally:
                client.close()
                if stream:stream.close()
                result.update(motion_frames=i,retained_samples=len(samples),samples=list(samples),
                              vertical_reference_y=vertical_reference,
                              vertical_reference_method="startup_face_position" if reference_capture else "image_center",
                              original_eye_guard_unchanged=hashlib.sha256(GUARD.read_bytes()).hexdigest()==digest)
                out.write_text(json.dumps(result,indent=2),encoding="utf-8")
                if a.status_file is not None:
                    write_status(a.status_file,{"running":False,"updated_epoch":time.time(),"result_path":str(out),
                                                "stop_confirmed":result.get("final",{}).get("active_mask")==0})
        print(json.dumps({k:v for k,v in result.items() if k!="samples"},indent=2))
if __name__=="__main__":main()
