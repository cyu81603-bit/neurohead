"""One bounded, replaceable USB Cam frame for local readers; never a camera owner."""
import base64
import json
import os
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
FRAME_PATH = ROOT / 'build' / 'usb_cam_shared.json'


def publish(packet, rgb, path=FRAME_PATH):
    import cv2
    if packet.get('error') or not packet.get('running') or rgb is None:
        return
    ok, jpeg = cv2.imencode('.jpg', cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR),
                            [cv2.IMWRITE_JPEG_QUALITY, 82])
    if not ok:
        return
    row = dict(schema=1, device='USB Cam', captured_monotonic=packet['frame_time'],
               vision=packet, jpeg=base64.b64encode(jpeg).decode('ascii'))
    path = Path(path)
    tmp = path.with_name(path.name + '.%d.tmp' % os.getpid())
    try:
        tmp.write_text(json.dumps(row, ensure_ascii=False), encoding='utf-8')
        os.replace(tmp, path)
    except OSError:
        # A busy reader or full disk must not terminate the existing tracking preview.
        return False
    return True


def read(path=FRAME_PATH, now=None, max_age=.75):
    path = Path(path)
    if path.stat().st_size > 2_000_000:
        raise ValueError('共享画面过大')
    row = json.loads(path.read_text(encoding='utf-8'))
    now = time.monotonic() if now is None else now
    if row.get('device') != 'USB Cam' or not 0 <= now-row['captured_monotonic'] <= max_age:
        raise ValueError('USB Cam画面已过期')
    if row['vision'].get('error') or not row['vision'].get('running'):
        raise ValueError('USB Cam未采集')
    return row
