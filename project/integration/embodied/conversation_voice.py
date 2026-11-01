"""Bounded microphone turns with background calibration and explicit send."""
import queue
import threading
import time
from collections import deque
import numpy as np
from audio_asr import VoiceASREngine


class TurnGate:
    def __init__(self, maximum=15., silence=.7):
        self.maximum=maximum;self.silence=silence;self.noise=30.;self.started=None
        self.last_voice=0.;self.calibration=[];self.trigger=0
    def step(self, rms, now):
        if len(self.calibration)<35:
            self.calibration.append(rms)
            self.noise=max(10.,float(np.percentile(self.calibration,65)))
            return 'calibrating'
        high=max(100.,self.noise*2.8);low=max(60.,self.noise*1.7)
        if self.started is None:
            if rms>=high:self.trigger+=1
            else:
                self.trigger=0;self.noise=.98*self.noise+.02*max(5.,rms)
            if self.trigger>=3:
                self.started=now;self.last_voice=now;self.trigger=0;return 'start'
            return 'idle'
        # Check the hard limit even while every frame still looks like speech.
        if now-self.started>=self.maximum:
            self.started=None;return 'maximum'
        if rms>=low:self.last_voice=now
        if now-self.last_voice>=self.silence:
            self.started=None;return 'end'
        return 'recording'
    def reset(self):self.started=None;self.trigger=0


class ConversationVoice:
    def __init__(self,on_speech_start=None,on_speech_cancel=None,on_speech_recognized=None,
                 on_status_change=None,on_barge_in=None,is_tts_playing=None):
        self.on_speech_start=on_speech_start;self.on_speech_cancel=on_speech_cancel
        self.on_speech_recognized=on_speech_recognized;self.status=on_status_change or (lambda *a:None)
        self.is_tts_playing=is_tts_playing or (lambda:False)
        self.recognizer=VoiceASREngine();self.is_enabled=False;self.is_running=False
        self.current_rms=0.;self.gate=TurnGate();self.pre=deque(maxlen=16)
        self.chunks=[];self.start_ts=0.;self.manual=False;self.stream=None
        self.lock=threading.RLock();self.jobs=queue.Queue(maxsize=2);self.cooldown=0.
        threading.Thread(target=self._decode,name='dialogue-recognizer',daemon=True).start()
    def set_enabled(self,value):
        self.is_enabled=bool(value)
        if not value:
            with self.lock:self._cancel()
    def _cancel(self):
        self.chunks=[];self.manual=False;self.gate.reset();self.pre.clear()
        if self.on_speech_cancel:self.on_speech_cancel()
    def start(self):
        if self.is_running:return self
        self.is_running=True;self.gate=TurnGate()
        threading.Thread(target=self._capture,name='dialogue-microphone',daemon=True).start()
        return self
    def stop(self):
        self.is_running=False;self.is_enabled=False
        with self.lock:self._cancel()
    def manual_begin(self):
        self.is_enabled=True;self.start()
        with self.lock:
            self._cancel();self.manual=True;self.start_ts=time.monotonic()
            if self.on_speech_start:self.on_speech_start(self.start_ts)
        self.status('MANUAL','正在录音，讲完点击“结束发送”，最长15秒')
    def manual_end(self):
        with self.lock:
            if self.manual:self._finish(time.monotonic())
    def _finish(self,now):
        raw=b''.join(self.chunks);start=self.start_ts
        self.chunks=[];self.manual=False;self.gate.reset();self.pre.clear()
        if len(raw)<9600:
            if self.on_speech_cancel:self.on_speech_cancel()
            self.status('SHORT','录音较短，请说完一句话后发送');return
        try:self.jobs.put_nowait((raw,start,now))
        except queue.Full:
            if self.on_speech_cancel:self.on_speech_cancel()
            self.status('BUSY','正在处理上一句话，请稍候')
    def _callback(self,indata,frames,clock,status):
        if not self.is_running or not self.is_enabled:return
        now=time.monotonic();raw=indata.tobytes();samples=indata.reshape(-1).astype(np.float32)
        rms=float(np.sqrt(np.mean((samples-np.mean(samples))**2)));self.current_rms=rms
        with self.lock:
            if self.manual:
                self.chunks.append(raw)
                if now-self.start_ts>=15. or len(self.chunks)>=469:self._finish(now)
                return
            if self.is_tts_playing() or now<self.cooldown:
                self._cancel();return
            phase=self.gate.step(rms,now)
            if phase=='start':
                self.start_ts=now-len(self.pre)*.032;self.chunks=list(self.pre)+[raw]
                if self.on_speech_start:self.on_speech_start(self.start_ts)
                self.status('SPEAKING','正在听你说，停顿约0.7秒后回答')
            elif phase in ('recording','end','maximum'):
                self.chunks.append(raw)
                if phase in ('end','maximum') or len(self.chunks)>=469:self._finish(now)
            else:self.pre.append(raw)
    def _capture(self):
        try:
            import sounddevice as sd
            with sd.InputStream(samplerate=16000,channels=1,dtype='int16',blocksize=512,callback=self._callback) as stream:
                self.stream=stream;self.status('LISTENING','语音监听已开启，正在适应背景声；可直接提问或用开始说话按钮')
                while self.is_running:time.sleep(.05)
        except Exception as exc:
            self.is_running=False;self.is_enabled=False;self.status('ERROR','麦克风打开失败：'+str(exc))
        finally:self.stream=None
    def _decode(self):
        while True:
            raw,start,end=self.jobs.get()
            try:
                self.status('RECOGNIZING','正在识别你刚才说的话…')
                text=self.recognizer.transcribe_pcm_bytes(self.recognizer.normalize_pcm(raw))
                if text:
                    self.status('RECOGNIZED','听到：'+text)
                    if self.on_speech_recognized:self.on_speech_recognized(text,start,end)
                else:
                    if self.on_speech_cancel:self.on_speech_cancel()
                    self.status('EMPTY','没有听清，请靠近麦克风，或点击开始说话后再发送')
            except Exception as exc:
                if self.on_speech_cancel:self.on_speech_cancel()
                self.status('ERROR','语音识别失败：'+str(exc))
    def notify_tts_stopped(self):
        self.cooldown=time.monotonic()+.65
        with self.lock:self._cancel()
