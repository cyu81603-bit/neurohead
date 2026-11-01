"""Shared detector adapter for OpenCV 4/5; no MediaPipe dependency."""
from pathlib import Path
import cv2

MODEL = Path(__file__).resolve().parents[2]/'data/models/face_detection_yunet_2023mar.onnx'


class FaceDetector:
    def __init__(self):
        if MODEL.is_file() and hasattr(cv2, 'FaceDetectorYN'):
            self.detector = cv2.FaceDetectorYN.create(str(MODEL), '', (320,320), .8, .3, 5000)
            self.name = 'yunet_2023mar'
        elif hasattr(cv2, 'CascadeClassifier'):
            self.detector = cv2.CascadeClassifier(cv2.data.haarcascades+'haarcascade_frontalface_default.xml')
            if self.detector.empty():
                raise RuntimeError('Haar classifier XML could not be loaded')
            self.name = 'haar_legacy'
        else:
            raise RuntimeError('OpenCV 5 needs the YuNet model. Run build/scripts/download_yunet.ps1 first.')

    def detect(self, frame):
        if self.name == 'haar_legacy':
            return self.detector.detectMultiScale(cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY),
                                                 scaleFactor=1.1, minNeighbors=6, minSize=(70,70))
        height, width = frame.shape[:2]
        # Keep aspect ratio; letterbox to the model's fixed 320x320 input.
        scale = min(320/width, 320/height)
        small = cv2.resize(frame, (max(1, round(width*scale)), max(1, round(height*scale))))
        padded = cv2.copyMakeBorder(small, 0, 320-small.shape[0], 0,
                                   320-small.shape[1], cv2.BORDER_CONSTANT, value=(0,0,0))
        _, faces = self.detector.detect(padded)
        boxes = []
        if faces is not None:
            for face in faces:
                x, y, w, h = [float(v)/scale for v in face[:4]]
                x0, y0 = max(0, round(x)), max(0, round(y))
                x1, y1 = min(width, round(x+w)), min(height, round(y+h))
                if x1 > x0 and y1 > y0:
                    boxes.append((x0, y0, x1-x0, y1-y0))
        return boxes
