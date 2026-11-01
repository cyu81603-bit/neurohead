#!/usr/bin/env python3
"""USB-camera face tracking for the NeuroHead UDP/PWM demonstrator.

Default mode is visual only. Add --send only after the mechanical safe range
has been verified with an oscilloscope and the head has clear travel.
"""
import argparse
import socket
import sys
import time

try:
    import cv2
except ImportError as exc:
    raise SystemExit("OpenCV is required: C:\\Python311\\python.exe -m pip install --user opencv-python") from exc

from send_neurohead_udp import PORT, make_frame
from face_detector import FaceDetector

CENTER_US = 1500
MIN_US = 1300
MAX_US = 1700
SEND_PERIOD_S = 0.05
EMA_ALPHA = 0.18


def clamp(value: float, lower: int, upper: int) -> int:
    return max(lower, min(upper, round(value)))


def largest_face(faces):
    return max(faces, key=lambda face: face[2] * face[3]) if len(faces) else None


def main() -> None:
    parser = argparse.ArgumentParser(description="Track a face and generate safe NeuroHead yaw/pitch targets.")
    parser.add_argument("--camera", type=int, default=0, help="USB camera index, default: 0")
    parser.add_argument("--host", default="192.168.10.20", help="AX7020 UDP address")
    parser.add_argument("--send", action="store_true", help="enable UDP transmission; default is preview only")
    parser.add_argument("--invert-yaw", action="store_true", help="reverse yaw direction after mechanical verification")
    parser.add_argument("--invert-pitch", action="store_true", help="reverse pitch direction after mechanical verification")
    parser.add_argument("--no-display", action="store_true", help="run without an OpenCV preview window")
    args = parser.parse_args()

    detector = FaceDetector()

    backend = cv2.CAP_DSHOW if sys.platform.startswith("win") else cv2.CAP_ANY
    capture = cv2.VideoCapture(args.camera, backend)
    if not capture.isOpened():
        raise SystemExit(f"Cannot open camera index {args.camera}. Check the USB camera and try another --camera index.")
    capture.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
    capture.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
    capture.set(cv2.CAP_PROP_FPS, 30)

    yaw_filtered = float(CENTER_US)
    pitch_filtered = float(CENTER_US)
    sequence = 0
    last_send = 0.0
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM) if args.send else None
    print("UDP sending enabled" if args.send else "Preview only. Add --send only after mechanical verification.")

    try:
        while True:
            ok, frame = capture.read()
            if not ok:
                raise RuntimeError("Camera frame capture failed.")
            height, width = frame.shape[:2]
            faces = detector.detect(frame)
            face = largest_face(faces)

            yaw_target = CENTER_US
            pitch_target = CENTER_US
            if face is not None:
                x, y, w, h = map(int, face)
                face_x = x + w / 2.0
                face_y = y + h / 2.0
                normalized_x = (face_x - width / 2.0) / (width / 2.0)
                normalized_y = (face_y - height / 2.0) / (height / 2.0)
                yaw_sign = -1.0 if args.invert_yaw else 1.0
                pitch_sign = -1.0 if args.invert_pitch else 1.0
                yaw_target = clamp(CENTER_US + yaw_sign * normalized_x * 200.0, MIN_US, MAX_US)
                pitch_target = clamp(CENTER_US + pitch_sign * normalized_y * 160.0, MIN_US, MAX_US)
                cv2.rectangle(frame, (x, y), (x + w, y + h), (0, 220, 0), 2)

            yaw_filtered += EMA_ALPHA * (yaw_target - yaw_filtered)
            pitch_filtered += EMA_ALPHA * (pitch_target - pitch_filtered)
            yaw_us = clamp(yaw_filtered, MIN_US, MAX_US)
            pitch_us = clamp(pitch_filtered, MIN_US, MAX_US)

            now = time.monotonic()
            if sock is not None and now - last_send >= SEND_PERIOD_S:
                timestamp_ms = int(now * 1000) & 0xFFFFFFFF
                sock.sendto(make_frame(sequence, yaw_us, pitch_us, timestamp_ms), (args.host, PORT))
                sequence = (sequence + 1) & 0xFFFF
                last_send = now

            status = f"yaw={yaw_us} us  pitch={pitch_us} us  {'SEND' if args.send else 'PREVIEW'}"
            cv2.putText(frame, status, (12, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.65, (0, 255, 255), 2)
            if not args.no_display:
                cv2.imshow("NeuroHead vision tracker — press q to quit", frame)
                if cv2.waitKey(1) & 0xFF == ord("q"):
                    break
    finally:
        capture.release()
        if sock is not None:
            sock.close()
        cv2.destroyAllWindows()


if __name__ == "__main__":
    main()
