"""GPL-2.0-or-later JSON-lines ViSP worker. No device/network/actuator IO."""
import json
import os
import sys
import time

if os.name == 'nt':
    _dll = os.add_dll_directory(os.path.join(sys.prefix, 'Library', 'bin'))
from visp_gaze_core import VispGaze


def main():
    gaze = VispGaze()
    print(json.dumps(dict(type='ready', backend='ViSP 3.7 Servo', executable=sys.executable)), flush=True)
    for line in sys.stdin:
        try:
            request = json.loads(line)
            began = time.perf_counter()
            pose = gaze.step(request.get('target'), request.get('frame_time'), request['now'])
            print(json.dumps(dict(type='pose', sequence=request['sequence'], input_time=request['now'],
                                  pose=pose, status=gaze.status, metrics=gaze.metrics,
                                  source_frame_id=request.get('source_frame_id'),
                                  source_session_id=request.get('source_session_id'),
                                  compute_ms=(time.perf_counter()-began)*1000), allow_nan=False), flush=True)
        except Exception as error:
            print(json.dumps(dict(type='error', error=str(error))), flush=True)
            return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
