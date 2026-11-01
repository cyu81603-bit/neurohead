"""Integrated operator UI; the existing NH22 controller remains the sole writer."""
import argparse
import base64
import json
import os
import queue
import sys
import threading
import time
import uuid
import tkinter as tk
from pathlib import Path
from tkinter import ttk

HERE = Path(__file__).resolve().parent
PROJECT = HERE.parents[1]
sys.path.insert(0, str(PROJECT/'src/pc'))
sys.path.insert(0, str(HERE))
import config
from intent_link import IntentLink
from vision_share import read as read_frame
from parallel_turn import turn_results


class BrainPanel:
    def __init__(self, parent, controller, services=True, listen=False):
        self.controller = controller
        self.speech_only=getattr(controller,'speech_only',False)
        self.window = tk.Toplevel(parent)
        self.window.title('NeuroHead 语音对话 v3 · 直接说话或文字提问')
        self.window.geometry('%dx%d+30+20' % (min(1000,self.window.winfo_screenwidth()-80),min(760,self.window.winfo_screenheight()-100)))
        self.events = queue.Queue()
        self.closed = threading.Event()
        self.query_lock = threading.Lock()
        self.intent_generation_lock = threading.RLock()
        self.generation = 0
        self.link = IntentLink(controller.control)
        self.brain = self.voice = self.speech = None
        self.buffer = None
        self.frame = None
        self.vision = {}
        self.last_key = None
        self.poll_id = None
        self.auto_listen=listen
        self.last_status_write=0.
        w = self.window
        tk.Label(w, text='看见你 · 听懂你 · 自然回应', font=('Microsoft YaHei UI', 19, 'bold')).pack(pady=10)
        self.status = tk.StringVar(value='正在准备本地对话；舵机保持原状态')
        tk.Label(w, textvariable=self.status, wraplength=1010).pack()
        row = tk.Frame(w); row.pack(pady=8)
        actions=[
            ('打开／复用 USB Cam', controller.open_camera),
            ('语音监听 开／关', self.toggle_mic),
            ('停止说话', self.interrupt),
        ]
        if not self.speech_only:actions[1:1]=[('开始说话＋表情联动',self.enable_link),('断开表情联动',self.disable_link)]
        for title, fn in actions:
            tk.Button(row, text=title, command=fn).pack(side='left', padx=5)
        self.details = tk.StringVar(value='麦克风默认关闭；表情联动默认关闭；相机由原预览独占采集。')
        tk.Label(w, textvariable=self.details, wraplength=1010).pack(pady=4)
        self.picture = tk.Label(w, text='点击“打开／复用 USB Cam”显示实时画面', width=90, height=9)
        self.picture.pack(pady=5)
        self.chat = tk.Text(w, height=11, wrap='word', font=('Microsoft YaHei UI', 11))
        self.chat.pack(fill='both', expand=True, padx=12)
        row = tk.Frame(w); row.pack(fill='x', padx=12, pady=10)
        self.entry = tk.Entry(row, font=('Microsoft YaHei UI', 12))
        self.entry.pack(side='left', fill='x', expand=True)
        self.entry.bind('<Return>', lambda e: self.ask_text())
        self.send = tk.Button(row, text='发送提问', command=self.ask_text)
        self.send.pack(side='left', padx=8)
        row=tk.Frame(w);row.pack(pady=5)
        self.manual_button=tk.Button(row,text='开始说话',command=self.manual_begin,width=16)
        self.manual_button.pack(side='left',padx=8)
        tk.Button(row,text='结束发送',command=self.manual_end,width=16).pack(side='left',padx=8)
        tk.Button(row,text='测试语音播放',command=self.test_speaker,width=16).pack(side='left',padx=8)
        tk.Label(w, text='本窗口仅负责听、说和文字问答，无舵机控制入口；原追踪窗口保持独立运行。' if self.speech_only else '舵机接线确认、会话开始和正面追踪仍在原主控操作。下颚自动动作保持禁用。').pack(pady=5)
        w.protocol('WM_DELETE_WINDOW', self.keep_window)
        if services:
            threading.Thread(target=self.prepare, name='prepare-brain', daemon=True).start()
        self.poll_id = w.after(80, self.poll)

    def event(self, kind, value):
        self.events.put((kind, value))

    def prepare(self):
        try:
            from video_buffer import TemporalVideoBuffer
            from qwen_brain import QwenEmbodiedBrain
            from speech_output import SpeechOutput
            from conversation_voice import ConversationVoice
            from ollama_local import ensure_service
            self.buffer = TemporalVideoBuffer()
            try:
                ensure_service()
            except Exception as exc:
                self.event('error', str(exc)+'；对话将明确显示离线兜底状态')
            self.brain = QwenEmbodiedBrain()
            self.speech = SpeechOutput(self.link, self.event)
            self.voice = ConversationVoice(
                on_speech_start=lambda ts: self.buffer.on_speech_start(ts),
                on_speech_cancel=lambda: self.buffer.on_speech_cancel(),
                on_speech_recognized=self.on_recognized,
                on_status_change=lambda k, msg: self.event('asr', msg),
                on_barge_in=lambda reason: self.interrupt_worker(),
                is_tts_playing=self.speech.is_playing)
            self.voice.set_enabled(False)
            self.event('ready', '对话已就绪，可输入文字；语音监听可按需开启')
            threading.Thread(target=self.read_camera, name='shared-camera-reader', daemon=True).start()
        except Exception as exc:
            self.event('error', str(exc))

    def read_camera(self):
        import cv2
        import numpy as np
        last_error = None
        while not self.closed.wait(.1):
            try:
                row = read_frame()
                key = (row['vision']['source_session_id'], row['vision']['frame_id'])
                if key == self.last_key:
                    continue
                frame = cv2.imdecode(np.frombuffer(base64.b64decode(row['jpeg']), np.uint8), cv2.IMREAD_COLOR)
                if frame is None:
                    raise ValueError('共享画面解码失败')
                self.last_key = key
                self.frame, self.vision = frame, row['vision']
                self.buffer.push_frame(frame, row['captured_monotonic'])
                self.event('frame', frame)
                last_error = None
            except (OSError, ValueError, KeyError) as exc:
                self.frame = None
                self.vision = {}
                if str(exc) != last_error:
                    self.event('camera_error', '等待共享USB Cam画面；在原主控打开预览')
                    last_error = str(exc)

    def enable_link(self):
        try:
            if self.controller.control.mode=='running' and hasattr(self.controller,'face_ready'):
                self.controller.control.enable_life(self.controller.face_ready.get())
            self.link.enable()
            self.status.set('表情已联动；语音能量驱动已批准的唇部和眉部')
        except Exception as exc:
            self.status.set(str(exc))

    def disable_link(self):
        try:
            self.link.disable()
            self.status.set('已断开对话表情联动，眼颈保持由原主控控制')
        except Exception as exc:
            self.status.set(str(exc))

    def toggle_mic(self):
        if not self.voice:
            self.status.set('语音识别仍在准备'); return
        if self.voice.is_enabled:
            self.voice.set_enabled(False)
            self.voice.stop()
            self.status.set('语音监听已关闭')
        else:
            self.voice.set_enabled(True)
            self.voice.start()
            self.status.set('语音监听已开启，可对机器人说话')

    def on_recognized(self, text, start, end):
        self.event('heard', text)
        threading.Thread(target=self.query,args=(text,start,end),daemon=True).start()

    def manual_begin(self):
        if not self.voice:
            self.status.set('语音引擎正在准备');return
        self.interrupt_worker()
        self.voice.manual_begin()
        self.manual_button.configure(text='正在录音…')

    def manual_end(self):
        if self.voice:self.voice.manual_end()
        self.manual_button.configure(text='开始说话')

    def test_speaker(self):
        if self.speech:self.speech.speak('你好，我已经准备好了。你可以直接和我说话，也可以点击开始说话，讲完再点击结束发送。')

    def ask_text(self):
        text = self.entry.get().strip()
        if not text: return
        self.entry.delete(0, 'end')
        self.event('heard', text)
        now = time.monotonic()
        threading.Thread(target=self.query, args=(text, now, now), daemon=True).start()

    def query(self, text, start, end):
        if not self.brain or not self.query_lock.acquire(False):
            self.event('error', '正在准备或回答上一句，请稍候'); return
        generation = self.generation
        self.event('busy', True)
        try:
            segment = self.buffer.extract_speech_video(start, end)
            # Old buffered images must not become a fresh visual answer after USB failure.
            if self.frame is None:
                segment = None
            vision=dict(self.vision)
            request=uuid.uuid4().hex
            cancelled=lambda:generation!=self.generation or self.closed.is_set()
            snapshot=self.brain.capture_context()
            for kind,result,error in turn_results(
                    lambda:self.brain.reply_multimodal(text,segment,vision,cancelled=cancelled,context_snapshot=snapshot),
                    lambda:self.brain.plan_actions(text,cancelled=cancelled,context_snapshot=snapshot),cancelled):
                with self.intent_generation_lock:
                    if cancelled():return
                    if error:
                        self.event('error',('对话生成' if kind=='reply' else '动作判断')+'失败：'+str(error));continue
                    if not result or result.get('cancelled'):continue
                    if kind=='action_decision':
                        result=dict(result)
                        result['action_dispatch']=self.link.dispatch_actions(result.get('actions',[]),request)
                        self.event('action_decision',result)
                    elif result and not result.get('cancelled'):
                        self.event('reply',result)
                        # Spoken text is the model's answer; it does not select
                        # or replay a gesture. PCM still drives approved lips.
                        self.speech.speak(result['reply_text'],'keep')
        except Exception as exc:
            self.event('error', str(exc))
        finally:
            self.query_lock.release()
            self.event('busy', False)

    def interrupt_worker(self):
        with self.intent_generation_lock:
            self.generation += 1
            self.link.cancel_actions()
            if self.speech: self.speech.stop()
        if self.voice: self.voice.notify_tts_stopped()
        if self.buffer: self.buffer.on_speech_cancel()

    def interrupt(self):
        self.interrupt_worker()
        self.status.set('已停止说话；已取消尚未完成的回复，颈部保持控制')

    def keep_window(self):
        self.interrupt()
        if self.voice and self.voice.is_enabled: self.toggle_mic()
        self.disable_link()
        self.status.set('对话已暂停，操作窗口保留')

    def poll(self):
        from PIL import Image, ImageTk
        while True:
            try: kind, value = self.events.get_nowait()
            except queue.Empty: break
            if kind == 'frame':
                rgb = Image.fromarray(value[:, :, ::-1]); rgb.thumbnail((640, 220))
                self.photo = ImageTk.PhotoImage(rgb)
                self.picture.configure(image=self.photo, text='', width=640, height=220)
            elif kind == 'camera_error':
                self.picture.configure(image='', text=value, width=90, height=9)
            elif kind == 'heard': self.chat.insert('end', '你：'+value+'\n')
            elif kind == 'reply':
                source = '本地大模型' if value.get('backend') == 'ollama' else '离线兜底'
                self.chat.insert('end', '机器人（'+source+'）：'+value['reply_text']+'\n\n')
                self.chat.see('end')
                self.status.set('%s · %.1f秒 · 表情%s · 视觉%s' % (source, value['latency_ms']/1000,
                    value['expression_label'], '已附加' if value['video_attached'] else '未附加'))
            elif kind == 'action_decision':
                self.details.set('动作判断：'+str(value.get('action_reason',''))+'；'+str(value.get('action_dispatch',{}).get('status','')))
            elif kind == 'busy': self.send.configure(state='disabled' if self.query_lock.locked() else 'normal')
            elif kind == 'tts_done':
                if self.voice: self.voice.notify_tts_stopped()
            elif kind in ('error', 'ready', 'asr', 'link_warning'):
                self.status.set(str(value))
                if kind=='ready' and self.auto_listen:
                    self.auto_listen=False;self.toggle_mic();self.test_speaker()
        self.details.set('语音监听%s · 表情联动%s · Ollama：F:\\Ollama · %s · 上下文%d' % (
            '开' if self.voice and self.voice.is_enabled else '关', '开' if self.link.enabled else '关',
            config.OLLAMA_MODEL, config.LLM_CONTEXT_WINDOW_TOKENS))
        if self.voice and not self.voice.manual:self.manual_button.configure(text='开始说话')
        if time.monotonic()-self.last_status_write>1:
            self.last_status_write=time.monotonic()
            status=dict(pid=os.getpid(),updated=time.time(),ready=self.brain is not None,
                        microphone_running=bool(self.voice and self.voice.is_running),
                        microphone_enabled=bool(self.voice and self.voice.is_enabled),
                        rms=float(self.voice.current_rms) if self.voice else 0.,
                        noise=float(self.voice.gate.noise) if self.voice else 0.,
                        speaking=bool(self.speech and self.speech.is_playing()),
                        linked=self.link.enabled,status=self.status.get())
            p=HERE/'build/dialogue_status.json';tmp=p.with_suffix('.tmp')
            try:tmp.write_text(json.dumps(status,ensure_ascii=False),encoding='utf-8');os.replace(tmp,p)
            except OSError:pass
        self.poll_id = self.window.after(80, self.poll)

    def shutdown(self):
        self.closed.set()
        self.interrupt_worker()
        if self.voice: self.voice.stop()
        self.link.disable()
        if self.poll_id: self.window.after_cancel(self.poll_id)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--self-test', action='store_true')
    parser.add_argument('--dialogue-only',action='store_true')
    parser.add_argument('--listen',action='store_true')
    parser.add_argument('--speech-only',action='store_true')
    args = parser.parse_args()
    if args.speech_only:
        class NoServoSession:
            mode='idle';extra={}
            def life_event(self,event):raise ValueError('纯对话窗口没有舵机控制能力')
        class SpeechOnlyController:
            speech_only=True
            control=NoServoSession()
            def open_camera(self):
                # Read an existing shared frame only; this window never owns a camera.
                try:read_frame()
                except (OSError,ValueError,KeyError):pass
        w=tk.Tk();w.withdraw()
        panel=BrainPanel(w,SpeechOnlyController(),listen=args.listen)
        w.mainloop();panel.shutdown();return
    if args.dialogue_only:
        from remote_controller import RemoteController
        w=tk.Tk();w.withdraw()
        panel=BrainPanel(w,RemoteController(),listen=args.listen)
        w.mainloop();panel.shutdown();return
    from lifelike_panel import LifelikePanel
    w = tk.Tk()
    if args.self_test: w.withdraw()
    class IntegratedPanel(LifelikePanel):
        def snapshot(self):
            return dict(super().snapshot(), integrated_frontend=True, integration_revision=63, frontal_response_revision=self.life_config.get('frontal_response_revision',0),left_lower_lid_guard_revision=self.life_config.get('left_lower_lid_guard_revision',0),expression_presets_revision=self.life_config.get('expression_presets_revision',0),action_library_revision=1,action_execution_revision=6,semantic_policy_revision=2,right_wink_revision=1,camera_lid_guard_revision=self.life_config.get('camera_lid_guard_revision',0),wink_side='right')
    controller = IntegratedPanel(w)
    w.title('NeuroHead v6.3 R6.7 · 正面追踪／右眼wink')
    controller.life_window.title('NeuroHead v6.3 R6.7 · 右眼wink／表情与动作库')
    from teammate_panel import TeammatePanel
    panel = TeammatePanel(w, controller, services=not args.self_test)
    panel.window.title('具身智能全链路主控台 · 同学原界面 / 右眼wink R6.7')
    if args.self_test:
        controller.life_window.withdraw(); panel.window.withdraw(); w.update_idletasks()
        controller.open_action_library();controller.action_window.withdraw();w.update_idletasks()
        assert controller.eye_gesture_delta.get()==300 and controller.eye_gesture_rate.get()==300
        assert controller.control.extra['eye_gesture']==dict(delta_us=300,rate_us_per_s=300)
        assert controller.head_gesture_yaw.get()==120 and controller.head_gesture_pitch.get()==100
        assert controller.action_window.winfo_reqheight()<=680
        assert controller.control.mode == 'idle' and controller.control.client is None
        assert not panel.link.enabled and panel.brain is None
        panel.shutdown(); controller.control.close(); w.destroy()
        print('EMBODIED_IDLE_NO_CAMERA_NO_MIC_NO_HARDWARE_PASS')
    else:
        w.mainloop()
        panel.shutdown()


if __name__ == '__main__': main()
