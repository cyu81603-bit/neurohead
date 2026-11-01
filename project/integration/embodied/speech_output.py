"""SAPI PCM and teammate character alignment, tied to the actual audio cursor."""
import threading
import time
import uuid
import numpy as np
from tts_lip_sync import synthesize_tts_pcm, compute_per_character_amplitudes
from articulation import speech_envelope


class SpeechOutput:
    def __init__(self, link, notify=lambda *a: None):
        self.link = link
        self.notify = notify
        self.cancel = threading.Event()
        self.worker = None
        self.playing = False
        self.generation = 0
        self.lock = threading.RLock()

    def is_playing(self):
        return self.playing

    def stop(self):
        with self.lock:
            self.generation += 1
            self.cancel.set()
            self.playing = False
            try:
                self.link.end()
            except Exception as exc:
                self.notify('link_warning', '表情联动结束失败，不影响语音停止：'+str(exc))

    def speak(self, text, expression=None):
        self.stop()
        with self.lock:
            gen = self.generation
            cancel = threading.Event()
            self.cancel = cancel
        def work():
            utterance = uuid.uuid4().hex
            begun = False
            try:
                pcm = synthesize_tts_pcm(text, 16000)
                if cancel.is_set():
                    return
                if len(pcm) == 0:
                    raise ValueError('Windows语音合成未生成音频，请检查中文语音包')
                records = compute_per_character_amplitudes(text, pcm, 16000)
                energies,energy_step=speech_envelope(pcm,16000,records)
                import sounddevice as sd
                self.notify('tts', {'characters': len(records), 'duration_s': len(pcm)/16000, 'records': records})
                # A bounded output queue: never queue the complete utterance ahead of the lips.
                with sd.OutputStream(samplerate=16000, channels=1, dtype='int16',
                                     blocksize=320, latency='low') as stream:
                    if cancel.is_set():
                        return
                    try:
                        begun = self.link.begin(utterance, expression, len(pcm)/16000) is not False
                        if not begun and getattr(self.link,'last_error',None):
                            self.notify('link_warning', self.link.last_error)
                    except Exception as exc:
                        self.notify('link_warning', '表情未就绪，继续纯语音播放：'+str(exc))
                    self.playing = True
                    cursor = [0.]
                    sender_done = threading.Event()
                    def send_energy():
                        try:
                            while not sender_done.is_set() and not cancel.is_set():
                                index=int(cursor[0]/(energy_step*1000))
                                if not begun:break
                                sent=self.link.energy(utterance, energies[index] if 0<=index<len(energies) else 0.)
                                if sent is False and getattr(self.link,'last_error',None):
                                    self.notify('link_warning',self.link.last_error);break
                                sender_done.wait(.05)
                        except Exception as exc:
                            self.notify('link_warning', '表情联动暂停，语音继续播放：'+str(exc))
                    sender=threading.Thread(target=send_energy,name='speech-intent-20hz',daemon=True)
                    sender.start()
                    try:
                        for start in range(0, len(pcm), 320):
                            if cancel.is_set():
                                stream.abort()
                                break
                            cursor[0]=start/16
                            ei=int(cursor[0]/(energy_step*1000))
                            self.notify('tts_cursor',dict(time_ms=cursor[0],energy=float(energies[ei]) if 0<=ei<len(energies) else 0.))
                            # Audio never waits for servo/network acknowledgement.
                            stream.write(pcm[start:start+320].reshape(-1, 1))
                    finally:
                        sender_done.set();sender.join(2.2)
            except Exception as exc:
                self.notify('error', str(exc))
            finally:
                if begun:
                    try:
                        self.link.end(utterance)
                    except Exception as exc:
                        self.notify('link_warning', '表情联动结束失败：'+str(exc))
                with self.lock:
                    if gen == self.generation:
                        self.playing = False
                self.notify('tts_done', None)
        previous = self.worker
        def serial_work():
            if previous and previous.is_alive():
                previous.join()
            if not cancel.is_set():
                work()
        self.worker = threading.Thread(target=serial_work, name='integrated-speech', daemon=True)
        self.worker.start()
