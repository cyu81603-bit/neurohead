from pathlib import Path
root=Path(r"F:\NeuroHead\builds\nh22_20261028")
p=root/"src/pc/eye_camera_feedback.py"
s=p.read_text(encoding="utf-8")
if "def acquire_run_lock(path):" in s:raise SystemExit("Stop support already applied")
s=s.replace('def main():','''def acquire_run_lock(path):
    import msvcrt
    handle=path.open("a+b")
    handle.seek(0,2)
    if handle.tell()==0:handle.write(b"0");handle.flush()
    handle.seek(0)
    try:msvcrt.locking(handle.fileno(),msvcrt.LK_NBLCK,1)
    except OSError:
        handle.close()
        raise RuntimeError("another eye feedback run is already active")
    return handle

def main():''',1)
s=s.replace('p.add_argument("--direction-evidence",type=Path)',
'''p.add_argument("--direction-evidence",type=Path)
    p.add_argument("--stop-file",type=Path)''')
s=s.replace('    log=ROOT/"build/external_vision.jsonl"',
'''    run_lock=acquire_run_lock(ROOT/"build/eye_feedback.lock")
    def check_operator_stop():
        if a.stop_file is not None and a.stop_file.exists():
            raise RuntimeError("operator stop requested")
    log=ROOT/"build/external_vision.jsonl"''',1)
s=s.replace('    while time.monotonic()<preflight_deadline:\n        try:',
'''    while time.monotonic()<preflight_deadline:
        check_operator_stop()
        try:''',1)
s=s.replace('        for i in range(total):\n            if time.monotonic()>deadline',
'''        for i in range(total):
            check_operator_stop()
            if time.monotonic()>deadline''',1)
s=s.replace('    finally:\n        try:\n            state=client.exchange(stop',
'''    except BaseException as exc:
        result["interruption_reason"]=str(exc)
        raise
    finally:
        try:
            state=client.exchange(stop''',1)
p.write_text(s,encoding="utf-8")
