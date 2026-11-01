"""One-shot external USB Cam + original YuNet preview, no robot/network control."""
import json,sys,time
from pathlib import Path
from external_camera import NamedUvcCapture
ROOT=Path(__file__).resolve().parents[2]
OLD=Path(r"F:\NeuroHead\workspace\neurohead_fpga_2026")
sys.path.insert(0,str(OLD/"src/pc_vision"))
from face_detector import FaceDetector
import cv2
def main():
    camera=NamedUvcCapture()
    try:
        frame=None
        for _ in range(5):
            ok,frame=camera.read()
            if not ok:raise RuntimeError("External camera failed; inspect build/external_camera_ffmpeg.log")
        detector=FaceDetector()
        before=time.perf_counter();faces=detector.detect(frame)
        ms=(time.perf_counter()-before)*1000
        preview=ROOT/"build/external_camera_preview.jpg"
        for x,y,w,h in faces:cv2.rectangle(frame,(x,y),(x+w,y+h),(0,220,60),2)
        cv2.putText(frame,"EXTERNAL: USB Cam",(8,22),cv2.FONT_HERSHEY_SIMPLEX,.55,(0,220,255),1)
        cv2.imwrite(str(preview),frame)
        report={"device_name":camera.config["device_name"],"device_path":camera.config["device_path"],
                "fallback_used":False,"width":int(frame.shape[1]),"height":int(frame.shape[0]),
                "detector":detector.name,"face_count":len(faces),"detection_ms":ms,
                "preview":str(preview),"robot_commands_sent":0}
        (ROOT/"build/external_camera_report.json").write_text(json.dumps(report,indent=2),encoding="utf-8")
        print(json.dumps(report,indent=2))
    finally:camera.release()
if __name__=="__main__":main()
