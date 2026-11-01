"""Intent-only integration. No board sockets, PWM, camera capture or model code."""
import math
import threading
from action_library import validate_actions


def expression_name(word):
    if word in ('wink_left','左眼wink'):raise ValueError('左眼wink因遮挡摄像头已停用，请使用右眼wink')
    return {'笑': 'happy', '微笑': 'smile', 'happy': 'happy', 'smile': 'smile',
            '难过': 'sad', 'sad': 'sad', 'wink': 'wink', 'wink_right': 'wink',
            '右眼wink': 'wink'}.get(word, 'neutral')


class IntentLink:
    def __init__(self, session):
        self.session = session
        self.enabled = False
        self.lock = threading.RLock()
        self.speaking_id = None
        self.last_error = None
        self.action_request = None
        self.last_action_result = None

    def _ready(self):
        return self.session.mode == 'running' and self.session.extra.get('life_state') in ('warming', 'active')

    def _send(self, event):
        try:
            if not self._ready():
                raise ValueError('表情模式未开启或会话已暂停')
            self.session.life_event(event)
            return True
        except Exception as exc:
            # Disabling an intent link must not interrupt audio or change gaze.
            self.enabled = False
            self.last_error = '表情联动已暂停，语音继续播放：'+str(exc)
            return False

    def enable(self):
        with self.lock:
            if not self._ready():
                raise ValueError('请先在舵机主控确认接线、开始会话并开启活人感')
            self.enabled = True
            self.last_error = None

    def disable(self):
        with self.lock:
            self.end()
            self.enabled = False

    def begin(self, utterance, expression, duration):
        with self.lock:
            self.speaking_id = utterance
            if not self.enabled:
                return False
            if expression=='keep':return self._ready()
            return self._send(dict(type='expression', name=expression_name(expression),
                                         duration_s=max(.1, min(20., float(duration)))))

    def energy(self, utterance, value):
        if not isinstance(value, (float, int)) or not math.isfinite(value) or not 0 <= value <= 1:
            raise ValueError('语音能量必须在0到1之间')
        with self.lock:
            if self.enabled and utterance == self.speaking_id:
                return self._send(dict(type='speech.energy', id=utterance, energy=value))

    def end(self, utterance=None):
        with self.lock:
            if utterance is not None and utterance != self.speaking_id:
                return
            if self.enabled and self.speaking_id is not None:
                self._send(dict(type='speech.end'))
            self.speaking_id = None
    def dispatch_actions(self,names,request_id):
        with self.lock:
            try:
                names=validate_actions(names)
                if not names:return dict(status='not_requested',actions=[])
                if self.session.mode!='running' or not self.session.extra.get('action_library_enabled'):
                    raise ValueError('动作库未开启；请在操作面板确认并开启')
                reply=self.session.life_event(dict(type='action',request_id=request_id,actions=names))
                self.action_request=request_id
                self.last_action_result=dict(status='accepted',request_id=request_id,actions=names,controller=reply)
            except Exception as exc:
                self.last_action_result=dict(status='rejected',request_id=request_id,actions=names,error=str(exc))
            return dict(self.last_action_result)
    def cancel_actions(self):
        with self.lock:
            if self.action_request is None:return
            try:self.session.life_event(dict(type='action.cancel',request_id=self.action_request))
            except Exception:pass
            self.action_request=None
