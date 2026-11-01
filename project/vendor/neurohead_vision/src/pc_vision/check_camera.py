#!/usr/bin/env python3
"""Read a short UVC sample and retain metadata only. Does not control servos."""
import argparse
from datetime import datetime
import json
from pathlib import Path
import sys
import time
import cv2
from face_detector import FaceDetector

ROOT = Path(__file__).resolve().parents[2]


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--camera', type=int, default=0)
    p.add_argument('--frames', type=int, default=30)
    args = p.parse_args()
    if not 1 <= args.frames <= 120:
        p.error('frames must be between 1 and 120')
    backend = cv2.CAP_DSHOW if sys.platform.startswith('win') else cv2.CAP_ANY
    cap = cv2.VideoCapture(args.camera, backend)
    result = dict(camera_index=args.camera, opencv=cv2.__version__,
                  opened=cap.isOpened(), requested_frames=args.frames,
                  frames_read=0, retained_image_frames=0, motion_commands=0,
                  physical_mount='unverified')
    t0 = time.perf_counter()
    try:
        if cap.isOpened():
            cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
            cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
            cap.set(cv2.CAP_PROP_FPS, 30)
            try:
                detector = FaceDetector()
                result['classifier_loaded'] = True
                result['detector'] = detector.name
            except RuntimeError as exc:
                detector = None
                result['classifier_loaded'] = False
                result['detector_error'] = str(exc)
            face_frames = 0
            for i in range(args.frames):
                ok, frame = cap.read()
                if not ok:
                    break
                result['frames_read'] += 1
                result['width'], result['height'] = frame.shape[1], frame.shape[0]
                if i % 5 == 0 and detector is not None:
                    faces = detector.detect(frame)
                    face_frames += int(len(faces) > 0)
            result['face_positive_sampled_frames'] = face_frames
    finally:
        cap.release()
    result['capture_and_sample_processing_s'] = round(time.perf_counter()-t0, 4)
    result['boundary'] = 'Short readiness sample includes startup/processing; not a sustained FPS benchmark. No image/video saved.'
    out = ROOT/'data/connection_checks'
    out.mkdir(parents=True, exist_ok=True)
    path = out/f"{datetime.now().strftime('%Y%m%d_%H%M%S_%f')}_camera.json"
    path.write_text(json.dumps(result, indent=2), encoding='utf-8')
    print(json.dumps(result, indent=2))
    print(f'Record: {path}')
    raise SystemExit(0 if result['frames_read'] == args.frames else 2)


if __name__ == '__main__':
    main()
