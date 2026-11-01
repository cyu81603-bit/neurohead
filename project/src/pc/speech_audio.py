"""Local speech-file envelope. Never opens a microphone or captures system audio."""
import json,math,subprocess,threading,time,wave
from pathlib import Path
import numpy as np
ROOT=Path(__file__).resolve().parents[2]
def envelope(wav_path,step=.02):
    with wave.open(str(wav_path),'rb') as w:
        rate=w.getframerate();channels=w.getnchannels();width=w.getsampwidth();count=w.getnframes()
        if width!=2 or count/rate>300:raise ValueError('Use PCM16 audio at most 5 minutes')
        data=np.frombuffer(w.readframes(count),dtype='<i2').astype(np.float64)/32768
    if not len(data):raise ValueError('Empty audio file')
    data=data.reshape(-1,channels).mean(axis=1);size=max(1,round(rate*step));raw=[]
    for start in range(0,len(data),size):raw.append(float(np.sqrt(np.mean(data[start:start+size]**2))))
    scale=max(.015,float(np.percentile(raw,90)));values=[0. if x<max(.003,scale*.07) else min(1.,math.sqrt(x/scale)) for x in raw]
    return values,step

def prepare_audio(path):
    path=Path(path)
    if not path.is_file():raise ValueError('Audio file not found')
    cfg=json.loads((ROOT/'config/camera.json').read_text(encoding='utf-8'));out=ROOT/'build/audio_cache'/('speech_'+str(time.time_ns())+'.wav');out.parent.mkdir(exist_ok=True)
    command=[cfg['ffmpeg'],'-hide_banner','-loglevel','error','-y','-protocol_whitelist','file,pipe','-i',str(path),'-t','300','-vn','-ac','1','-ar','16000','-c:a','pcm_s16le',str(out)]
    result=subprocess.run(command,capture_output=True,timeout=60,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
    if result.returncode:raise ValueError('Audio decode failed: '+result.stderr.decode('utf-8',errors='replace')[-500:])
    frames,step=envelope(out);return out,frames,step

class AudioPlayer:
    def __init__(self,session,notify=lambda kind,text:None):self.session=session;self.notify=notify;self.worker=None;self.cancel=threading.Event();self.audio_lock=threading.Lock()
    def play(self,path):
        if self.worker is not None and self.worker.is_alive():raise ValueError('Stop current playback before starting another')
        self.cancel.clear()
        def work():
            token=None
            try:
                self.notify('audio','正在准备语音文件');wav,frames,step=prepare_audio(path)
                if self.cancel.is_set():return
                token=self.session.speech_timeline(frames,step,Path(path).name)
                import winsound
                with self.audio_lock:
                    if self.cancel.is_set():return
                    winsound.PlaySound(str(wav),winsound.SND_FILENAME|winsound.SND_NODEFAULT|winsound.SND_ASYNC)
                self.notify('audio','播放中：'+Path(path).name);self.cancel.wait(len(frames)*step)
                with self.audio_lock:winsound.PlaySound(None,0)
                self.notify('audio','语音结束')
            except Exception as exc:self.notify('error',str(exc))
            finally:
                try:
                    if token is not None:self.session.life_event({'type':'speech.end','token':token})
                except Exception:pass
        self.worker=threading.Thread(target=work,name='speech-playback',daemon=True);self.worker.start()
    def stop(self):
        self.cancel.set()
        try:
            import winsound
            with self.audio_lock:winsound.PlaySound(None,0)
        finally:
            try:self.session.life_event({'type':'speech.end'})
            except Exception:pass
