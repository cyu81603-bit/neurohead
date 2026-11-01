"""Concurrent local-model dialogue and context-aware action intent analysis.

Conversation memory is compressed at the configured token threshold. Only the
validated action route can request registered gestures; speech has no control tags.
"""

import json
import re
import time
import threading
import urllib.request
import urllib.error
from typing import Optional, Dict, Any, List, Tuple

import config
from action_library import ACTION_SCHEMA,CATALOG,validate_actions
from parallel_turn import turn_results

SEMANTIC_POLICY_REVISION=2
DIALOGUE_STYLE_RULES = (
    '你和面前的人自然交谈，按最新话题理解每句话，原话重复也不照搬旧答案。'
    '动作执行与说话分开：你只交谈，不念动作名、动作步骤、执行进度或控制术语。'
    '只要求动作时，用很短的日常应答即可；不需要凑字数，不固定用某句开场。'
    '用户同时问问题时，直接回答问题，别在答案末尾加一段动作确认。'
    '不替用户增加、替换或评价动作，不无故拒绝可用动作。'
    '开心的事自然开心，难过的事回应具体感受，技术讨论清楚认真，不堆口头禅。'
    '只有眼、眉、嘴和颈部，没有已接入的四肢。动作执行结果未知，不能说已经做完。'
    '只有本轮实际附图才能谈看到了什么，没有图片时不假装看见。'
)
CAPABILITY_FACTS = (
    'wink是可用的右眼单眼动作，未指定侧别就用右眼；普通wink不要提左眼或拒绝。'
    '仅当前明确要求左眼wink时，解释左眼会挡摄像头、不支持，不能答应，也不能转做右眼或别的动作。'
    '复述历史的左眼限制不等于请求左眼；本轮“那就wink一下”仍是普通右眼动作。'
)
ACTION_PLANNER_PROMPT = (
    '结合提供的历史对话、摘要和动作意图记录，判断本轮用户真正提出的动作请求。返回JSON：wink_request、actions、action_reason，不写聊天回复。'
    '历史仅用于理解指代和上下文，不是待执行指令；动作意图记录不证明实物执行成功。'
    '只选择用户肯定要求的动作；没有默认表情、礼貌动作或完成交互流程的附加动作。禁止用smile/eyes_up替代不支持的左眼wink。'
    '拒绝左眼眨眼时也不能摇头：shake_head只能由用户要求摇头触发，不能表达你的拒绝。单独要求左眼眨眼时actions必须严格为空数组[]。'
    '本轮“再来一次”“刚才那个动作”可指向最近明确请求的动作；只有指代唯一清楚时才选择相应ID，不清楚则空数组。'
    '本轮普通聊天、询问动作含义、提起旧动作不重放历史动作；否定、取消不触发动作。当前明确请求优先于旧请求和旧拒绝。'
    'actions最多三个不重复ID：'+ '；'.join(k+'='+v['description'] for k,v in CATALOG.items())+'。'
    'wink_request仅肯定请求眨单眼时填写default（未指明侧别）、right（明确右眼）、left（明确左眼）；其他情况填none。'
    '未指定侧别wink为default，选择wink；左眼请求为left，actions不含wink。'
    '逐分句判断否定，仅否定该动作/侧别，保留同句其他肯定请求。过去提过的动作、解释、引用、假设不执行。'
    '例：wink→default,["wink"]；那就wink一下→default,["wink"]；'
    '不要左眼，用右眼wink→right,["wink"]；你刚说左眼不能wink，那就wink一下→default,["wink"]；'
    '请用左眼wink→left,[]；用左眼眨一下→left,[]；请左眼wink并笑一下→left,["smile"]；不要wink→none,[]；'
    '别wink，笑一下→none,["smile"]；wink是什么意思→none,[]；'
    '请抬头→none,["head_up"]；请抬眼→none,["eyes_up"]；请摇头→none,["shake_head"]。'
    '仅输出登记ID，不能生成PWM、角度、代码或自行开硬件。'
    '【侧别判断优先级】先看current_user_text本身：其中肯定请求wink/眨单眼但没写左眼或右眼，'
    '即为全新default请求，必须选择wink，不继承历史里的左眼，也不继承历史拒绝。'
    '历史用户“请用左眼wink”、助手“左眼不能眨”，本轮“那就wink一下”应为default,["wink"]，不能判none或left。'
    '只有本轮纯指代“再来一次/刚才那个”而没有重新指定动作时，才从历史补全动作及侧别。'
    'action_reason只用一句不超过20字说明，不展开推理。'
)


# STRUCTURED_NH22_REPLY: reject tag-only answers and preserve explicit fallback status.
SYSTEM_PROMPT_QWEN35 = (
    '你是面对面交谈的机器人伙伴。只输出自然的中文口语，不输出JSON、控制标签、旁白或舞台动作。'
    '对话通常一到三句；简单应答可以只有几个字。只纠正明显同音错字，不扩写用户意图。'
    + DIALOGUE_STYLE_RULES
)

class QwenEmbodiedBrain:
    """
    本地 Ollama Qwen3.5:4b 多模态视觉、语音上下文纠错与情感决策中心
    上下文窗口、压缩阈值由config配置，两路共享轮次开始时的上下文。
    """

    def __init__(
        self,
        chat_url: str = config.OLLAMA_CHAT_URL,
        model: str = config.OLLAMA_MODEL,
        context_window_tokens: int = config.LLM_CONTEXT_WINDOW_TOKENS,
        compress_threshold_tokens: int = config.LLM_COMPRESS_THRESHOLD_TOKENS,
        keep_recent_messages: int = config.LLM_KEEP_RECENT_MESSAGES,
    ):
        self.chat_url = chat_url
        self.model = model
        self.context_window_tokens = int(context_window_tokens)
        self.compress_threshold_tokens = int(compress_threshold_tokens)
        self.keep_recent_messages = max(4, int(keep_recent_messages))

        self._lock = threading.Lock()
        # Context capture must never wait for an in-flight model request.
        self._history_lock = threading.RLock()
        self._action_context = []
        self.is_ready = False
        self.compressed_summary: str = ""
        self.compression_count: int = 0
        self.current_context_tokens: int = 0

        self.chat_history: List[Dict[str, Any]] = [
            {"role": "system", "content": SYSTEM_PROMPT_QWEN35}
        ]
        self.current_context_tokens = self.estimate_messages_tokens(self.chat_history)

        # 启动后台显存预热线程
        threading.Thread(target=self._warmup_worker, daemon=True, name="Qwen35Warmup").start()

    @staticmethod
    def estimate_text_tokens(text: str) -> int:
        """
        快速估算中英文混合文本的 Token 数（用于监控配置的压缩阈值和窗口）：
        汉字与全角字符约按 1.5 token/字估算，ASCII 字符约按 0.35 token/字符估算。
        """
        if not text:
            return 0
        cjk_count = sum(1 for ch in text if "\u4e00" <= ch <= "\u9fff" or ord(ch) > 255)
        ascii_count = len(text) - cjk_count
        return max(1, int(round(cjk_count * 1.5 + ascii_count * 0.35)) + 4)

    @classmethod
    def estimate_messages_tokens(cls, messages: List[Dict[str, Any]]) -> int:
        total = 0
        for m in messages:
            total += cls.estimate_text_tokens(str(m.get("content", "")))
            if m.get("images"):
                total += 256 * len(m["images"])
        return total

    def _warmup_worker(self) -> None:
        try:
            payload = {
                "model": self.model,
                "messages": [{"role": "user", "content": "你好"}],
                "stream": False,
                "think": False,
                "keep_alive": config.OLLAMA_KEEP_ALIVE,
                "options": {
                    "num_ctx": self.context_window_tokens,
                    "num_predict": 8,
                }
            }
            req = urllib.request.Request(
                self.chat_url,
                data=json.dumps(payload).encode("utf-8"),
                headers={"Content-Type": "application/json"}
            )
            with urllib.request.urlopen(req, timeout=45.0) as _:
                self.is_ready = True
        except Exception as e:
            print(f"[QwenEmbodiedBrain] 预热提示: {e}")

    def clear_history(self) -> None:
        with self._lock, self._history_lock:
            self._action_context = []
            self.compressed_summary = ""
            self.compression_count = 0
            self.chat_history = [
                {"role": "system", "content": SYSTEM_PROMPT_QWEN35}
            ]
            self.current_context_tokens = self.estimate_messages_tokens(self.chat_history)

    def capture_context(self):
        """One immutable-by-convention turn snapshot shared by both routes."""
        with self._history_lock:
            return dict(history=[dict(m) for m in self.chat_history],
                        summary=self.compressed_summary,
                        action_intents=[dict(m,actions=list(m['actions'])) for m in self._action_context])

    def get_turn_count(self) -> int:
        return sum(1 for m in self.chat_history if m.get("role") == "user")

    def get_context_stats(self) -> Dict[str, Any]:
        return {
            "context_tokens": self.current_context_tokens,
            "compress_threshold_tokens": self.compress_threshold_tokens,
            "context_window_tokens": self.context_window_tokens,
            "compression_count": self.compression_count,
            "message_count": len(self.chat_history),
        }

    def _compress_history_over_threshold_locked(self, use_llm_summary: bool = True) -> bool:
        """
        当上下文累计超过配置阈值 (compress_threshold_tokens) 时自动触发：
        将较早的历史对话压缩为高密度【前文记忆摘要】，同时完整保留最近 keep_recent_messages 条原始对话，
        确保上下文始终运行在配置窗口的高效区间内。
        """
        est_tokens = self.estimate_messages_tokens(self.chat_history)
        self.current_context_tokens = max(self.current_context_tokens, est_tokens)
        if self.current_context_tokens <= self.compress_threshold_tokens:
            return False

        # self.chat_history[0] 固定为 system prompt
        non_sys = self.chat_history[1:]
        if len(non_sys) <= self.keep_recent_messages:
            # 若单条历史极长导致超 64K，则截断最旧消息的内容并生成摘要
            old_part = non_sys[: max(1, len(non_sys) // 2)]
            recent_part = non_sys[max(1, len(non_sys) // 2) :]
        else:
            old_part = non_sys[: -self.keep_recent_messages]
            recent_part = non_sys[-self.keep_recent_messages :]

        # 提取旧对话的关键信息
        raw_lines = []
        for m in old_part:
            role_cn = "用户" if m.get("role") == "user" else "机器人"
            txt = str(m.get("content", "")).strip()
            if txt.startswith("[前文自动压缩记忆摘要]"):
                raw_lines.append(txt)
            else:
                # 单条提取前 180 字核心语义用于摘要汇总
                short_txt = txt[:180].replace("\n", " ")
                raw_lines.append(f"{role_cn}: {short_txt}")

        joined_digest = "\n".join(raw_lines)
        if len(joined_digest) > 3500:
            joined_digest = joined_digest[:1750] + "\n...\n" + joined_digest[-1750:]

        new_summary = ""
        if use_llm_summary:
            try:
                sum_prompt = (
                    "请将以下具身机器人与用户的早期历史对话压缩为一段 300 字以内的【核心上下文记忆摘要】，"
                    "重点保留最新主题、用户偏好及事实结论；标明话题切换。不要把旧动作请求、旧拒绝或旧模型误判当成本轮指令和永久规则：\n\n"
                    f"{joined_digest}"
                )
                payload = {
                    "model": self.model,
                    "messages": [{"role": "user", "content": sum_prompt}],
                    "stream": False,
                    "think": False,
                    "keep_alive": config.OLLAMA_KEEP_ALIVE,
                    "options": {
                        "num_ctx": self.context_window_tokens,
                        "temperature": 0.2,
                        "num_predict": 220,
                    }
                }
                req = urllib.request.Request(
                    self.chat_url,
                    data=json.dumps(payload).encode("utf-8"),
                    headers={"Content-Type": "application/json"}
                )
                with urllib.request.urlopen(req, timeout=12.0) as resp:
                    resp_json = json.loads(resp.read().decode("utf-8"))
                    new_summary = resp_json.get("message", {}).get("content", "").strip()
            except Exception:
                new_summary = ""

        if not new_summary:
            # 确定性极速结构化压缩回退
            new_summary = joined_digest[:1200]

        with self._history_lock:
            self.compression_count += 1
            self.compressed_summary = (
                f"[前文自动压缩记忆摘要 (第{self.compression_count}次压缩)]：\n{new_summary}"
            )
            summary_msg = {"role": "system", "content": self.compressed_summary}
            self.chat_history = [self.chat_history[0], summary_msg] + recent_part
            self.current_context_tokens = self.estimate_messages_tokens(self.chat_history)
        return True

    def reply_multimodal(
        self,
        user_text: str,
        video_segment: Optional[Dict[str, Any]] = None,
        tracking_state: Optional[Dict[str, Any]] = None,
        timeout: float = config.LLM_TIMEOUT_S,
        cancelled=None,
        context_snapshot=None,
    ) -> Dict[str, Any]:
        """
        执行一次多模态问答推理（含语音转文字上下文纠错与 配置的上下文管理）：
        :param user_text: 用户语音转写 (ASR) 或文本提问
        :param video_segment: TemporalVideoBuffer.extract_speech_video() 返回的 [t_start-5s, t_end] 视频数据
        :param tracking_state: 队友追踪算法返回的实时人脸位置/状态摘要
        """
        t0 = time.monotonic()
        user_text = (user_text or "").strip()
        if not user_text:
            return {
                "reply_text": "我在听呢，请说出你的问题吧。",
                "corrected_user_text": "",
                "expression": None,
                "expression_label": "无",
                "gaze_mode": "track_face",
                "actions": [], "action_reason": "没有动作请求", "action_parse_error": None,
                "latency_ms": 0.0,
                "video_attached": False,
                "video_span_s": 0.0,
                "context_tokens": self.current_context_tokens,
                "context_window_tokens": self.context_window_tokens,
                "compression_count": self.compression_count,
            }

        # 组装追踪状态、时序视频说明与语音转文字纠错提示
        context_lines = [
            "[本轮用户原话可能来自语音转写或文字输入；仅纠正明显同音错字，不改写用户意图。]",
            "[本轮动作状态：另一条通路独立处理动作，这里没有收到执行结果。只说交谈内容，不播报动作、不描述身体正在或已经怎样动。用户同时问问题时实质回答问题；只请求动作时简短接话，不添加其他动作。]",
        ]
        video_b64 = None
        video_span_s = 0.0
        if video_segment and video_segment.get("valid") and video_segment.get('storyboard_b64'):
            video_b64 = video_segment.get("storyboard_b64")
            video_span_s = float(video_segment.get("span_seconds", 0.0))
            pre_s = float(video_segment.get("pre_speech_seconds", 0.0))
            spk_s = float(video_segment.get("speaking_seconds", 0.0))
            n_frm = int(video_segment.get("frame_count", 0))
            context_lines.append(
                f"[视觉输入：已附带用户开口前 {pre_s:.1f} 秒至说话结束（说话持续 {spk_s:.1f} 秒，共 {video_span_s:.1f} 秒/{n_frm} 帧）的 6 帧时序视频拼图]"
            )
        else:
            context_lines.append('[本轮没有提供图片或视频；无法判断画面内容。不要声称已看过画面、画面里没有某物或未捕捉到某物。]')

        if tracking_state:
            face_cnt = tracking_state.get("face_count", 0)
            target = tracking_state.get("target")
            if face_cnt > 0 and target is not None:
                context_lines.append(
                    f"[追踪传感器：画面中检测到 {face_cnt} 张人脸，归一化中心偏差 dx={target[0]:+.2f}, dy={target[1]:+.2f}]"
                )
            else:
                context_lines.append("[追踪传感器：当前画面未检测到正脸]")

        full_user_prompt = "\n".join(context_lines) + '\n' + json.dumps({'current_user_text':user_text},ensure_ascii=False)

        user_msg: Dict[str, Any] = {"role": "user", "content": full_user_prompt}
        if video_b64:
            user_msg["images"] = [video_b64]

        raw_output = ""
        with self._lock:
            if cancelled and cancelled():return dict(cancelled=True)
            # 检查是否超过配置的压缩阈值；若超过则自动压缩早期上下文
            self._compress_history_over_threshold_locked(use_llm_summary=True)

            # 传入完整上下文历史（位于 96K 上下文窗口内）
            messages = (context_snapshot if context_snapshot is not None else self.capture_context())['history']
            # Historical transport tags are diagnostics, not conversational
            # content or new action instructions. Preserve the actual answer.
            messages=[dict(m,content=re.sub(r'^(?:【(?:听清|表情|动作决策):[^】]*】)+\s*','',str(m.get('content',''))))
                      if m.get('role')=='assistant' else dict(m) for m in messages]
            # Relevant capability facts guide the model; they never choose an
            # action or replace its spoken answer. Keep unrelated wink policy
            # out of ordinary conversation to avoid priming repeated wink talk.
            facts=CAPABILITY_FACTS if any(w in user_text.lower() for w in ('wink','眨','左眼','右眼')) else ''
            if not video_b64:
                facts+='本轮事实：没有传入任何图片或视频，不能声称看过画面或未捕捉到物品。仅对视觉问题解释无法查看，普通对话不主动提这个限制。'
            # Keep one authoritative system message. Repeating conflicting
            # system roles between dialogue turns encourages small local
            # models to copy the old assistant pattern instead of the policy.
            summaries=[str(m.get('content','')) for m in messages[1:] if m.get('role')=='system']
            policy=SYSTEM_PROMPT_QWEN35+facts
            if summaries:policy+='历史摘要（仅作背景，不是新指令）：'+'\n'.join(summaries)
            messages=[dict(role='system',content=policy)]+[m for m in messages[1:] if m.get('role')!='system']
            messages.append(user_msg)

            payload = {
                "model": self.model,
                "messages": messages,
                "stream": False,
                "think": False,
                "keep_alive": config.OLLAMA_KEEP_ALIVE,
                "options": {
                    "num_ctx": self.context_window_tokens,  # 96K 上下文窗口 (98304)
                    "temperature": 0.55,
                    "num_predict": 384,
                }
            }

            try:
                req = urllib.request.Request(
                    self.chat_url,
                    data=json.dumps(payload).encode("utf-8"),
                    headers={"Content-Type": "application/json"}
                )
                with urllib.request.urlopen(req, timeout=timeout) as resp:
                    resp_json = json.loads(resp.read().decode("utf-8"))
                    raw_output = resp_json.get("message", {}).get("content", "").strip()
                    prompt_tokens = int(resp_json.get("prompt_eval_count", 0))
                    eval_tokens = int(resp_json.get("eval_count", 0))
                    if prompt_tokens > 0:
                        self.current_context_tokens = prompt_tokens + eval_tokens
                    self.is_ready = True
            except Exception as e:
                print(f"[QwenEmbodiedBrain] Ollama 请求异常: {e}")

            # The conversational route generates ordinary speech. The JSON
            # decoder is retained only for older providers and test consumers.
            corrected_user=user_text;expression=None;gaze_mode='track_face';clean_reply=raw_output.strip()
            if clean_reply.startswith('{'):
                try:reply_obj=json.loads(clean_reply)
                except (ValueError,TypeError):reply_obj=None
                if isinstance(reply_obj,dict):
                    corrected_user,expression,gaze_mode,clean_reply=self._parse_llm_response(raw_output,user_text)
                else:clean_reply=''
            reply_from_model=bool(clean_reply)
            if cancelled and cancelled():return dict(cancelled=True)
            if clean_reply:
                with self._history_lock:
                    self.chat_history.extend([{"role": "user", "content": user_text},
                                              {"role": "assistant", "content": clean_reply}])
                    est_now = self.estimate_messages_tokens(self.chat_history)
                    self.current_context_tokens = max(self.current_context_tokens, est_now)
                # 若追加后超过配置阈值，立即执行压缩
                if self.current_context_tokens > self.compress_threshold_tokens:
                    self._compress_history_over_threshold_locked(use_llm_summary=True)
            else:
                clean_reply='这次没有收到有效回答，请再说一次。'

        dt_ms = (time.monotonic() - t0) * 1000.0
        return {
            "reply_text": clean_reply,
            "backend": "ollama" if reply_from_model else "offline_fallback",
            "corrected_user_text": corrected_user or user_text,
            "expression": expression,
            "expression_label": expression if expression is not None else "无",
            "gaze_mode": gaze_mode,
            "latency_ms": round(dt_ms, 1),
            "video_attached": bool(video_b64),
            "video_span_s": video_span_s,
            "context_tokens": self.current_context_tokens,
            "context_window_tokens": self.context_window_tokens,
            "compression_count": self.compression_count,
        }

    def plan_actions(self,user_text,timeout=config.LLM_TIMEOUT_S,context_snapshot=None,cancelled=None):
        start=time.monotonic()
        if cancelled and cancelled():return dict(cancelled=True)
        if not str(user_text or '').strip():return dict(actions=[],action_reason='没有动作请求',wink_request='none',action_parse_error=None,latency_ms=0.)
        snapshot=context_snapshot if context_snapshot is not None else self.capture_context()
        actions,reason,side,error=self._plan_current_actions(user_text,timeout,snapshot)
        if cancelled and cancelled():return dict(cancelled=True)
        if not error:
            with self._history_lock:
                self._action_context.append(dict(user_text=user_text,actions=list(actions),wink_request=side,
                                                 status='intent_only_execution_unconfirmed'))
                self._action_context=self._action_context[-6:]
        return dict(actions=actions,action_reason=reason,wink_request=side,action_parse_error=error,latency_ms=round((time.monotonic()-start)*1000,1))

    def infer_multimodal(self,user_text,video_segment=None,tracking_state=None,timeout=config.LLM_TIMEOUT_S):
        # Read-only combined interface retained for evaluation/other consumers.
        # The live UI consumes each route as soon as it completes.
        start=time.monotonic();reply={};decision={}
        snapshot=self.capture_context()
        for kind,result,error in turn_results(
                lambda:self.reply_multimodal(user_text,video_segment,tracking_state,timeout,context_snapshot=snapshot),
                lambda:self.plan_actions(user_text,timeout,context_snapshot=snapshot)):
            if error:raise error
            if kind=='reply':reply=result
            else:decision=result
        result=dict(reply,**{k:v for k,v in decision.items() if k!='latency_ms'})
        result.update(reply_latency_ms=reply.get('latency_ms'),action_latency_ms=decision.get('latency_ms'),latency_ms=round((time.monotonic()-start)*1000,1))
        return result

    def _plan_current_actions(self,user_text,timeout,snapshot):
        # Bound planner background independently of chat history size. Never
        # include system policies, images, or this turn's concurrently generated reply.
        budget=max(128,self.context_window_tokens-self.estimate_text_tokens(ACTION_PLANNER_PROMPT)
                   -self.estimate_text_tokens(user_text)-600)
        def bounded(text,tokens):
            text=str(text)
            while self.estimate_text_tokens(text)>tokens and text:text=text[len(text)//8+1:]
            return text
        summary=bounded(snapshot.get('summary',''),min(200,budget//6))
        intents=[dict(user_text=bounded(m['user_text'],70),actions=list(m['actions']),
                      wink_request=m.get('wink_request'),status='intent_only_execution_unconfirmed')
                 for m in snapshot.get('action_intents',[])[-4:]]
        budget-=self.estimate_text_tokens(summary)+self.estimate_text_tokens(json.dumps(intents,ensure_ascii=False))
        history=[]
        for m in reversed(snapshot['history']):
            if m.get('role') not in ('user','assistant'):continue
            if budget<40 or len(history)>=12:break
            content=bounded(m.get('content',''),min(250,budget-20))
            history.insert(0,dict(role=m['role'],content=content))
            budget-=self.estimate_text_tokens(content)+20
        context=dict(history_summary=summary,recent_dialogue=history,
                     recent_action_intents=intents,current_user_text=user_text)
        payload=dict(model=self.model,stream=False,think=False,keep_alive=config.OLLAMA_KEEP_ALIVE,
            messages=[dict(role='system',content=ACTION_PLANNER_PROMPT),
                      dict(role='user',content=json.dumps(context,ensure_ascii=False))],
            format=dict(type='object',properties=dict(
                action_reason=dict(type='string',maxLength=120),
                wink_request=dict(type='string',enum=['none','default','right','left']),actions=ACTION_SCHEMA),
                required=['action_reason','wink_request','actions']),
            options=dict(num_ctx=self.context_window_tokens,temperature=0.,num_predict=160))
        try:
            req=urllib.request.Request(self.chat_url,data=json.dumps(payload).encode('utf-8'),headers={'Content-Type':'application/json'})
            with urllib.request.urlopen(req,timeout=timeout) as response:raw=json.loads(response.read().decode('utf-8'))['message']['content']
            actions,reason,error=self._parse_action_decision(raw)
            obj=json.loads(raw)
            if not isinstance(obj,dict):raise ValueError('动作决策必须为JSON对象')
            return actions,reason,obj.get('wink_request'),error
        except (OSError,ValueError,TypeError,KeyError) as exc:
            return [],'本轮动作分析失败，不执行',None,str(exc)

    @staticmethod
    def _parse_action_decision(raw_text):
        try:
            obj=json.loads(raw_text)
            if not isinstance(obj,dict):raise ValueError('模型动作决策必须为JSON对象')
            # Legacy replies lacking the new field remain conversation-only.
            names=validate_actions(obj.get('actions',[]))
            side=obj.get('wink_request')
            if side is not None:
                if side not in ('none','default','right','left'):raise ValueError('wink_request必须是登记的侧别意图')
                if side in ('none','left'):names=[name for name in names if name!='wink']
                elif 'wink' not in names:names=validate_actions(names+['wink'])
            reason=obj.get('action_reason','未提供动作选择理由')
            return names,str(reason)[:240],None
        except (ValueError,TypeError) as exc:return [],'动作决策无效，不执行',str(exc)

    @classmethod
    def _parse_llm_response(
        cls,
        raw_text: str,
        user_text: str
    ) -> Tuple[str, Optional[str], str, str]:
        """
        解析大模型输出，提取并严格校验：
        1. corrected_user: 大模型结合上下文还原后的用户真实语句
        2. expression: 仅限 "笑"、"难过"、"wink" 或 None；执行仍需舵机主控许可
        3. gaze_mode : "track_face" | "nod" | "tilt_left" | "tilt_right" | "keep_current"
        4. clean_reply: 剔除所有控制标签与特殊符号后的纯净播报文本
        """
        if raw_text:
            try:
                obj = json.loads(raw_text)
            except (ValueError, TypeError):
                obj = None
            if isinstance(obj, dict):
                reply = obj.get('reply_text')
                if not isinstance(reply, str) or not reply.strip():
                    return user_text, None, 'track_face', ''
                expr = obj.get('expression')
                corrected = obj.get('corrected_user_text')
                return (corrected if isinstance(corrected, str) and corrected.strip() else user_text,
                        expr if expr in config.ALLOWED_EXPRESSIONS else None,
                        'track_face', reply.strip()[:600])
        corrected_user: str = user_text
        expression: Optional[str] = None
        gaze_mode: str = "track_face"
        expr_match = None

        if raw_text:
            # 0. 提取 【听清:...】 或 【纠错:...】
            corr_match = re.search(r"[【\[]\s*(?:听清|纠错|原意)\s*[:：]\s*([^】\]]+)[】\]]", raw_text)
            if corr_match:
                c_val = corr_match.group(1).strip(" 「」\"'“”‘’")
                if c_val:
                    corrected_user = c_val

            # 1. 提取 【表情:...】
            expr_match = re.search(r"[【\[]\s*表情\s*[:：]\s*([^】\]]+)[】\]]", raw_text)
            if expr_match:
                val = expr_match.group(1).strip()
                if val.lower() in ('wink','wink_right','右眼wink'):
                    expression = 'wink'
                elif "笑" in val or "开心" in val or "高" in val or "喜" in val:
                    expression = "笑"
                elif "难过" in val or "伤心" in val or "悲" in val or "遗憾" in val or "哭" in val:
                    expression = "难过"
                else:
                    expression = None

            # 2. 提取 【动作:...】 或 【视线:...】
            act_match = re.search(r"[【\[]\s*(?:动作|视线)\s*[:：]\s*([^】\]]+)[】\]]", raw_text)
            if act_match:
                act_val = act_match.group(1).strip().lower()
                if act_val in ("track_face", "nod", "tilt_left", "tilt_right", "keep_current", "neutral"):
                    gaze_mode = act_val
                elif "左" in act_val:
                    gaze_mode = "tilt_left"
                elif "右" in act_val:
                    gaze_mode = "tilt_right"
                elif "点头" in act_val:
                    gaze_mode = "nod"

        else:
            # 当 Ollama 未启动时的本地同音词纠错兜底
            homophone_map = {
                "巨神智能": "具身智能",
                "健身智能": "具身智能",
                "多机": "舵机",
                "动机": "舵机",
                "南国": "难过",
                "小一个": "笑一个",
                "前五苗食品": "前五秒视频",
            }
            for wrong, right in homophone_map.items():
                if wrong in corrected_user:
                    corrected_user = corrected_user.replace(wrong, right)

        # 清理标签与思考块，得到纯净口语
        cleaned = raw_text or ""
        cleaned = re.sub(r"<think>.*?</think>", "", cleaned, flags=re.DOTALL | re.IGNORECASE)
        cleaned = re.sub(r"[【\[][^】\]]*[】\]]", "", cleaned)
        cleaned = re.sub(r"\([^)]*\)|（[^）]*）", "", cleaned)
        cleaned = re.sub(r"[`#*~>|]", "", cleaned)
        emoji_re = re.compile(
            r"[\U00010000-\U0010ffff\U00002600-\U000027ff\U00002300-\U000023ff\U00002b50-\U00002b55\U0000200d\U0000fe0f]+",
            flags=re.UNICODE
        )
        cleaned = emoji_re.sub("", cleaned)
        cleaned = re.sub(r"\s+", " ", cleaned).strip()
        cleaned = re.sub(r"^[，,。！!？?、；;\s]+", "", cleaned).strip()

        # 若模型未显式标注表情，基于语义进行兜底判定（仍严格限制在 "笑" / "难过" / None）
        if expression is None and (expr_match is None):
            combined = f"{user_text} {corrected_user} {cleaned}"
            sad_keywords = ("难过", "伤心", "悲伤", "遗憾", "抱歉", "可惜", "节哀", "失败了", "别灰心", "心疼", "哭")
            smile_keywords = ("开心", "高兴", "太棒", "恭喜", "哈哈", "愉快", "荣幸", "真棒", "欢喜", "笑", "祝贺")
            if any(k in combined for k in sad_keywords):
                expression = "难过"
            elif any(k in combined for k in smile_keywords):
                expression = "笑"

        # 最终白名单硬校验：确保只有 "笑"、"难过" 或 None
        if expression not in config.ALLOWED_EXPRESSIONS:
            expression = None

        # 若触发了情绪表情但未指定特殊头部动作，可联动队友的颈部预设姿态
        ref_text = f"{user_text} {corrected_user}"
        if gaze_mode == "track_face":
            if "左" in ref_text and ("看" in ref_text or "倾" in ref_text):
                gaze_mode = "tilt_left"
            elif "右" in ref_text and ("看" in ref_text or "倾" in ref_text):
                gaze_mode = "tilt_right"

        return corrected_user, expression, gaze_mode, cleaned
