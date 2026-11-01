"""Nonblocking JSON-lines client for the isolated ViSP model-only worker."""
from datetime import datetime
import json
import math
from pathlib import Path
import queue
import subprocess
import threading
import time
from visp_runtime import ROOT, PYTHON, environment


class VispGazeProxy:
    def __init__(self):
        self.pose = dict(neck_pan=0., neck_tilt=0., neck_roll=0.,
                         eye_pan=0., eye_tilt=0., jaw_open=0.)
        self.status = 'controller_starting'
        self.sequence = 0
        self.result = None
        self.applied_result = None
        self.input_source = None
        self.error = ''
        self.failure = None
        self.started = time.monotonic()
        self.ready = threading.Event()
        self.response = threading.Event()
        self.stop = threading.Event()
        self.lock = threading.Lock()
        self.requests = queue.Queue(maxsize=1)
        self.process = None
        self.log_dir = ROOT/'data/visp_runtime_runs'/datetime.now().strftime('%Y%m%d_%H%M%S_%f')
        self.log_dir.mkdir(parents=True)
        self.stderr = (self.log_dir/'native.stderr.log').open('wb')
        try:
            self.process = subprocess.Popen(
                [str(PYTHON), '-u', str(Path(__file__).with_name('visp_worker.py'))],
                cwd=ROOT, env=environment(), stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                stderr=self.stderr, text=True, encoding='utf-8', bufsize=1,
                creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        except OSError as error:
            self.error = str(error)
            self.status = 'controller_error'
            return
        self.reader = threading.Thread(target=self._read, name='visp_reader', daemon=True)
        self.writer = threading.Thread(target=self._write, name='visp_writer', daemon=True)
        self.reader.start()
        self.writer.start()

    def _fail(self, message, exit_code=None):
        """Keep the first cause; a subsequent EOF must not hide a timeout."""
        with self.lock:
            if not self.error:
                self.error = message+'; see '+str(self.log_dir)
                self.failure = dict(reason=message, observed_at=datetime.now().astimezone().isoformat(),
                    uptime_s=time.monotonic()-self.started,
                    worker_pid=self.process.pid if self.process else None,
                    child_exit_code=exit_code, request_sequence=self.sequence,
                    last_response_sequence=self.result.get('sequence') if self.result else None,
                    hardware_motion_commands_sent=0)
            elif (self.failure is not None and exit_code is not None
                  and self.failure.get('child_exit_code') is None):
                self.failure['child_exit_code'] = exit_code
            if self.failure is not None:
                try:
                    (self.log_dir/'worker_failure.json').write_text(
                        json.dumps(self.failure,indent=2),encoding='utf-8')
                except OSError:
                    pass  # The in-memory error still freezes the model.

    def _read(self):
        try:
            for line in self.process.stdout:
                if self.stop.is_set():
                    break
                try:
                    row = json.loads(line)
                except ValueError:
                    continue  # Some optional native libraries print startup notices.
                if row.get('type') == 'ready':
                    (self.log_dir/'runtime.json').write_text(json.dumps(row, indent=2))
                    self.ready.set()
                elif row.get('type') == 'pose':
                    values = row.get('pose', {})
                    if set(values) != set(self.pose) or not all(math.isfinite(x) for x in values.values()):
                        raise ValueError('Invalid native pose')
                    with self.lock:
                        self.result = row
                    self.response.set()
                elif row.get('type') == 'error':
                    raise RuntimeError(row.get('error', 'Native worker failed'))
            if not self.stop.is_set():
                try:
                    code = self.process.wait(timeout=.2)
                except subprocess.TimeoutExpired:
                    code = None
                self._fail('ViSP worker ended',code)
        except Exception as error:
            if not self.stop.is_set():
                self._fail(str(error),self.process.poll())

    def _write(self):
        try:
            while not self.stop.is_set():
                with self.lock:
                    if self.error:
                        return
                if not self.ready.wait(.1):
                    continue
                began=time.monotonic()
                source=self.input_source
                if source:
                    packet=source()
                    valid=packet.get('running',True) and not packet.get('error')
                    request=self._request(packet.get('target') if valid else None,
                                          packet.get('frame_time') if valid else None,began)
                    request['source_frame_id']=packet.get('frame_id')
                    request['source_session_id']=packet.get('source_session_id')
                else:
                    try:
                        request = self.requests.get(timeout=.1)
                    except queue.Empty:
                        continue
                self.response.clear()
                self.process.stdin.write(json.dumps(request, allow_nan=False)+'\n')
                self.process.stdin.flush()
                if not self.response.wait(.5) and not self.stop.is_set():
                    self._fail('ViSP response timed out; virtual pose held')
                    self.process.terminate()
                    return
                if source:self.stop.wait(max(0.,.05-(time.monotonic()-began)))
        except Exception as error:
            if not self.stop.is_set():
                self._fail(str(error),self.process.poll())

    def set_input_source(self,source):
        """Poll latest camera/model inputs independently of expensive 3D frames."""
        self.input_source=source

    def _request(self,target,frame_time,now):
        if not (isinstance(target, (tuple, list)) and len(target) == 2 and
                all(isinstance(x, (int, float)) and math.isfinite(x) for x in target)):
            target = None
        if not isinstance(frame_time, (int, float)) or not math.isfinite(frame_time):
            frame_time = None
        self.sequence += 1
        return dict(sequence=self.sequence, target=target, frame_time=frame_time, now=now)

    def step(self, target, frame_time, now):
        if self.stop.is_set():
            raise RuntimeError('ViSP client is closed')
        if self.input_source is None:
            request=self._request(target,frame_time,now)
            try:
                self.requests.put_nowait(request)
            except queue.Full:
                try:
                    self.requests.get_nowait()
                except queue.Empty:
                    pass
                self.requests.put_nowait(request)
        with self.lock:
            row, error = self.result, self.error
        if error:
            self.status = 'controller_error'
        elif row and 0 <= now-row['input_time'] <= .5:
            self.pose = dict(row['pose'])
            self.status = row['status']
            self.applied_result=row
        else:
            self.status = 'controller_stale' if self.ready.is_set() else 'controller_starting'
        return dict(self.pose)

    def diagnostics(self):
        with self.lock:
            row, error = self.applied_result, self.error
        return dict(backend='visp_native', ready=self.ready.is_set(), error=error,
                    log_dir=str(self.log_dir), request_sequence=self.sequence,
                    response_sequence=row['sequence'] if row else None,
                    input_time=row['input_time'] if row else None,
                    compute_ms=row['compute_ms'] if row else None,
                    source_frame_id=row.get('source_frame_id') if row else None,
                    source_session_id=row.get('source_session_id') if row else None,
                    metrics=row['metrics'] if row else None,
                    worker_failure=dict(self.failure) if self.failure else None,
                    hardware_motion_commands_sent=0)

    def close(self):
        if self.stop.is_set():
            return
        self.stop.set()
        if self.process:
            try:
                self.process.stdin.close()
            except (OSError, ValueError):
                pass
            try:
                self.process.wait(timeout=.5)
            except subprocess.TimeoutExpired:
                self.process.terminate()
                try:
                    self.process.wait(timeout=1.)
                except subprocess.TimeoutExpired:
                    self.process.kill()
                    self.process.wait(timeout=1.)
            self.reader.join(timeout=.5)
            self.writer.join(timeout=.5)
        self.stderr.close()
