import json,subprocess,time
from pathlib import Path
root=Path(r"F:\NeuroHead\builds\nh22_20261028")
cfg=json.loads((root/"config/camera.json").read_text())
command=[cfg["ffmpeg"],"-hide_banner","-nostdin","-f","dshow","-video_size","640x480","-framerate","30",
         "-vcodec","mjpeg","-i","video=USB Cam","-frames:v","1","-threads","1","-y",str(root/"build/external_camera_test.jpg")]
start=time.perf_counter()
try:
    result=subprocess.run(command,stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=15,
                          creationflags=getattr(subprocess,"CREATE_NO_WINDOW",0))
    (root/"build/camera_capture_debug.log").write_bytes(result.stderr)
    print("exit",result.returncode,"elapsed",time.perf_counter()-start)
    print(result.stderr.decode(errors="replace")[-3000:])
except subprocess.TimeoutExpired as exc:
    (root/"build/camera_capture_debug.log").write_bytes(exc.stderr or b"")
    print("CAPTURE_TIMEOUT",time.perf_counter()-start)
