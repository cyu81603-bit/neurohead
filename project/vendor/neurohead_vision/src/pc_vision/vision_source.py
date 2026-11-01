"""Latest-frame UVC/YuNet worker for model-only visualization. No network IO."""
import threading
import time
import uuid


class VisionSource:
    def __init__(self,camera_index=0,capture_factory=None,detector_factory=None):
        self.camera_index=camera_index
        self.session_id=uuid.uuid4().hex
        self.capture_factory=capture_factory
        self.detector_factory=detector_factory
        self.lock=threading.Lock()
        self.stop_event=threading.Event()
        self.packet=dict(frame_id=0,frame_time=None,target=None,face_count=0,box=None,
                         error=None,running=False,camera_index=camera_index,source_session_id=self.session_id)
        self.frame=None
        self.thread=None

    def start(self):
        self.thread=threading.Thread(target=self._run,name='neurohead_uvc',daemon=True)
        self.thread.start()
        return self

    def _run(self):
        cap=None
        try:
            import cv2
            import sys
            from face_detector import FaceDetector
            cv2.setNumThreads(2)
            factory=self.capture_factory or (lambda:cv2.VideoCapture(
                self.camera_index,cv2.CAP_DSHOW if sys.platform.startswith('win') else cv2.CAP_ANY))
            cap=factory()
            if not cap.isOpened():raise RuntimeError(f'Cannot open camera {self.camera_index}')
            cap.set(cv2.CAP_PROP_FRAME_WIDTH,640)
            cap.set(cv2.CAP_PROP_FRAME_HEIGHT,480)
            cap.set(cv2.CAP_PROP_FPS,15)
            detector=(self.detector_factory or FaceDetector)()
            frame_id=0
            while not self.stop_event.is_set():
                started=time.monotonic()
                ok,frame=cap.read()
                acquired=time.monotonic()
                if not ok:raise RuntimeError('Camera frame read failed; model will return to neutral')
                height,width=frame.shape[:2]
                detection_started=time.perf_counter()
                faces=detector.detect(frame)
                detection_ms=(time.perf_counter()-detection_started)*1000
                box=max(faces,key=lambda b:b[2]*b[3]) if len(faces) else None
                target=None
                if box is not None:
                    x,y,w,h=map(int,box)
                    target=[(x+w/2-width/2)/(width/2),(y+h/2-height/2)/(height/2)]
                    cv2.rectangle(frame,(x,y),(x+w,y+h),(0,210,80),2)
                    cv2.line(frame,(width//2,height//2),(int(x+w/2),int(y+h/2)),(0,180,255),2)
                cv2.drawMarker(frame,(width//2,height//2),(0,220,255),cv2.MARKER_CROSS,18,1)
                cv2.putText(frame,'VISION -> VIRTUAL MODEL ONLY',(8,22),cv2.FONT_HERSHEY_SIMPLEX,.5,(0,220,255),1)
                frame_id+=1
                packet=dict(frame_id=frame_id,frame_time=acquired,target=target,
                            face_count=len(faces),box=list(map(int,box)) if box is not None else None,
                            error=None,running=True,camera_index=self.camera_index,
                            width=width,height=height,detector=detector.name,
                            source_session_id=self.session_id,
                            detection_ms=detection_ms)
                with self.lock:self.packet,self.frame=packet,cv2.cvtColor(frame,cv2.COLOR_BGR2RGB)
                self.stop_event.wait(max(0,.0667-(time.monotonic()-started)))
        except Exception as exc:
            with self.lock:
                self.packet=dict(self.packet,error=str(exc),running=False,target=None)
        finally:
            if cap is not None:cap.release()
            with self.lock:self.packet=dict(self.packet,running=False)

    def snapshot(self):
        with self.lock:return dict(self.packet),self.frame.copy() if self.frame is not None else None

    def close(self):
        self.stop_event.set()
        if self.thread:self.thread.join(timeout=1)
