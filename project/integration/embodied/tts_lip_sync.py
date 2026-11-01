"""
tts_lip_sync.py - 大模型语音合成、逐字平均振幅提取与实时张嘴同步引擎
严格实现需求 4：
1. 大模型说话时的音频通过 Windows SAPI SpMemoryStream 合成为 16kHz 16-bit 单声道 PCM 波形。
2. 采用【有声段 (Voiced Islands) 与标点分句动态对齐算法】，自动剥离句首尾及标点符号处的静音间隙，
   精确记录回答中【每个字】的平均振幅 (avg_amplitude)、归一化张嘴幅度 (norm_amplitude: 0~1)、
   对应下颌舵机脉宽 (jaw_pulse_us) 以及每个字的起止时间戳 [start_ms, end_ms]。
3. 将【每个字的平均振幅表】与【表情词汇 (笑 / 难过 / 无)】打包一起输入下一级调度器，
   并在语音播放过程中实时驱动下一级张嘴大小。
"""

import re
import time
import threading
from typing import List, Dict, Any, Optional, Callable, Tuple
import numpy as np

import config

try:
    import win32com.client
    import pythoncom
    HAS_SAPI = True
except ImportError:
    HAS_SAPI = False

try:
    import sounddevice as sd
    HAS_SD = True
except ImportError:
    HAS_SD = False


PUNCTUATION_SET = set("，。！？、；：“”‘’（）()【】[]《》<>.,!?;:\"'-\n\r\t ")


def extract_clauses_and_chars(text: str) -> Tuple[List[str], List[str]]:
    """
    将文本按标点切分为发音分句 (clauses)，并提取所有需要发音的字列表 (chars)
    """
    if not text:
        return [], []
    clauses = [
        "".join(ch for ch in seg if ch not in PUNCTUATION_SET)
        for seg in re.split(r"[，。！？、；：“”‘’（）()【】\[\]《》<>.,!?;:\"' \t\r\n-]+", text)
    ]
    clauses = [c for c in clauses if c]
    chars = [ch for clause in clauses for ch in clause]
    return clauses, chars


def synthesize_tts_pcm(text: str, sample_rate: int = config.TTS_SAMPLE_RATE) -> np.ndarray:
    """
    使用 Windows SAPI SpMemoryStream 在内存中直接合成 16kHz 16-bit 单声道 PCM 波形
    """
    if not text or not HAS_SAPI:
        return np.zeros(0, dtype=np.int16)

    try:
        pythoncom.CoInitialize()
        voice = win32com.client.Dispatch("SAPI.SpVoice")
        stream = win32com.client.Dispatch("SAPI.SpMemoryStream")
        # Type 18 = SAFT16kHz16BitMono (16000Hz, 16-bit, 1 channel)
        stream.Format.Type = 18
        voice.AudioOutputStream = stream
        voice.Rate = 1
        voice.Volume = 100
        voice.Speak(text, 0)
        raw_bytes = bytes(stream.GetData())
        if not raw_bytes:
            return np.zeros(0, dtype=np.int16)
        return np.frombuffer(raw_bytes, dtype=np.int16).copy()
    except Exception as e:
        print(f"[tts_lip_sync] SAPI 合成异常: {e}")
        return np.zeros(0, dtype=np.int16)
    finally:
        try:
            pythoncom.CoUninitialize()
        except Exception:
            pass


def compute_per_character_amplitudes(
    text: str,
    pcm_int16: np.ndarray,
    sample_rate: int = config.TTS_SAMPLE_RATE
) -> List[Dict[str, Any]]:
    """
    核心算法：计算大模型说话音频中【每个字】的平均振幅与对应张嘴大小。
    步骤：
    1. 提取所有分句 (clauses) 与单字序列 (chars)。
    2. 计算 10ms 帧长 (160 samples @ 16kHz) 的音频能量包络，检测有声发音段 (Voiced Islands)，
       自动剔除首尾静音与句间标点停顿静音。
    3. 将每个分句的字对齐到有声发音段，计算每个字时间窗内的：
       - avg_amplitude : 原始 PCM 平均绝对振幅 (0 ~ 32767)
       - rms_amplitude : 均方根振幅
       - norm_amplitude: 归一化张嘴大小 (0.0 ~ 1.0，与模型张嘴大小直接成正比)
       - jaw_pulse_us  : 映射到 NH21 下颌舵机通道的目标脉宽 (us)
       - start_ms / end_ms : 该字对应的音频时间区间
    """
    clauses, chars = extract_clauses_and_chars(text)
    if not chars:
        return []

    jaw_cfg = config.FACE_CHANNEL_CONFIG["jaw_mouth"]
    jaw_neutral = int(jaw_cfg["neutral_us"])
    jaw_max_delta = int(jaw_cfg["max_open_delta_us"])
    jaw_min = int(jaw_cfg["min_us"])
    jaw_max = int(jaw_cfg["max_us"])

    # 若无音频数据，生成安全回退振幅表
    if pcm_int16 is None or pcm_int16.size == 0:
        fallback = []
        for idx, ch in enumerate(chars):
            fallback.append({
                "index": idx,
                "char": ch,
                "avg_amplitude": 800.0,
                "rms_amplitude": 1000.0,
                "norm_amplitude": 0.35,
                "jaw_pulse_us": jaw_neutral + int(round(0.35 * jaw_max_delta)),
                "start_ms": idx * 200,
                "end_ms": (idx + 1) * 200,
            })
        return fallback

    pcm_f32 = pcm_int16.astype(np.float32)
    frame_len = max(1, sample_rate // 100)  # 10ms = 160 samples @ 16kHz
    n_frames = len(pcm_f32) // frame_len

    if n_frames < 2:
        avg_a = float(np.mean(np.abs(pcm_f32)))
        return [{
            "index": i,
            "char": ch,
            "avg_amplitude": round(avg_a, 1),
            "rms_amplitude": round(avg_a, 1),
            "norm_amplitude": 0.3,
            "jaw_pulse_us": jaw_neutral + int(round(0.3 * jaw_max_delta)),
            "start_ms": i * 180,
            "end_ms": (i + 1) * 180,
        } for i, ch in enumerate(chars)]

    frames = pcm_f32[:n_frames * frame_len].reshape(n_frames, frame_len)
    rms_env = np.sqrt(np.mean(frames ** 2, axis=1))
    max_rms = float(np.percentile(rms_env, 96)) if n_frames > 0 else 1.0
    max_rms = max(max_rms, 100.0)

    # 有声阈值：高于峰值能量的 4.5% 视为发音段
    active_mask = rms_env > (max_rms * 0.045)

    # 提取连续有声发音岛 (桥接 <= 80ms = 8帧的字间微停顿；> 80ms 视为标点停顿分界)
    islands: List[Tuple[int, int]] = []
    in_island = False
    island_start_f = 0
    gap_f = 0

    for f_idx, is_act in enumerate(active_mask):
        if is_act:
            if not in_island:
                in_island = True
                island_start_f = f_idx
            gap_f = 0
        else:
            if in_island:
                gap_f += 1
                if gap_f > 8:
                    end_f = max(island_start_f + 1, f_idx - gap_f + 1)
                    islands.append((island_start_f * frame_len, end_f * frame_len))
                    in_island = False
                    gap_f = 0

    if in_island:
        end_f = max(island_start_f + 1, n_frames - gap_f)
        islands.append((island_start_f * frame_len, end_f * frame_len))

    if not islands:
        islands = [(0, len(pcm_f32))]

    # 为每个字分配对应的采样点区间 (s_sample, e_sample)
    char_intervals: List[Tuple[str, int, int]] = []

    if len(islands) == len(clauses):
        # 理想情况：标点分句数量与有声发音岛数量完全一致，逐句对齐
        for clause, (s_idx, e_idx) in zip(clauses, islands):
            bounds = np.linspace(s_idx, e_idx, len(clause) + 1, dtype=int)
            for i, ch in enumerate(clause):
                char_intervals.append((ch, int(bounds[i]), int(bounds[i + 1])))
    else:
        # 通用情况：在所有有声发音岛的总有效长度上按字数映射，同样跳过所有静音间隙
        island_lengths = [max(1, e - s) for (s, e) in islands]
        total_voiced_samples = sum(island_lengths)
        cum_lengths = np.cumsum([0] + island_lengths)

        def _voiced_offset_to_pcm_idx(v_offset: float) -> int:
            v_offset = max(0.0, min(float(total_voiced_samples), v_offset))
            for k, (s_i, e_i) in enumerate(islands):
                if v_offset <= cum_lengths[k + 1] or k == len(islands) - 1:
                    local_off = v_offset - cum_lengths[k]
                    return int(min(e_i, s_i + round(local_off)))
            return islands[-1][1]

        v_bounds = np.linspace(0, total_voiced_samples, len(chars) + 1)
        for i, ch in enumerate(chars):
            s_pcm = _voiced_offset_to_pcm_idx(v_bounds[i])
            e_pcm = _voiced_offset_to_pcm_idx(v_bounds[i + 1])
            if e_pcm <= s_pcm:
                e_pcm = min(len(pcm_f32), s_pcm + frame_len)
            char_intervals.append((ch, s_pcm, e_pcm))

    # 计算每个字的平均振幅与张嘴脉宽
    char_records: List[Dict[str, Any]] = []
    raw_avgs = []
    for ch, s_pcm, e_pcm in char_intervals:
        seg = pcm_f32[s_pcm:e_pcm]
        if seg.size > 0:
            avg_amp = float(np.mean(np.abs(seg)))
            rms_amp = float(np.sqrt(np.mean(seg ** 2)))
        else:
            avg_amp = 0.0
            rms_amp = 0.0
        raw_avgs.append((ch, s_pcm, e_pcm, avg_amp, rms_amp))

    # 以本句 95% 分位字平均振幅作为满幅张嘴基准，确保每个字的张嘴区分度自然鲜明
    ref_peak_avg = float(np.percentile([x[3] for x in raw_avgs], 95)) if raw_avgs else 1500.0
    ref_peak_avg = max(ref_peak_avg, 300.0)

    for idx, (ch, s_pcm, e_pcm, avg_amp, rms_amp) in enumerate(raw_avgs):
        norm_amp = float(np.clip(avg_amp / (ref_peak_avg * 1.05), 0.0, 1.0))
        jaw_us = int(np.clip(
            jaw_neutral + round(norm_amp * jaw_max_delta),
            jaw_min,
            jaw_max
        ))
        start_ms = int(round(s_pcm * 1000.0 / sample_rate))
        end_ms = int(round(e_pcm * 1000.0 / sample_rate))
        char_records.append({
            "index": idx,
            "char": ch,
            "avg_amplitude": round(avg_amp, 1),
            "rms_amplitude": round(rms_amp, 1),
            "norm_amplitude": round(norm_amp, 3),
            "jaw_pulse_us": jaw_us,
            "start_ms": start_ms,
            "end_ms": end_ms,
        })

    return char_records


class TTSLipSyncEngine:
    """
    TTS 语音合成、逐字振幅分析与实时声画同步播报器
    """

    def __init__(
        self,
        sample_rate: int = config.TTS_SAMPLE_RATE,
        on_next_stage_packet: Optional[Callable[[Dict[str, Any]], None]] = None,
        on_playback_finished: Optional[Callable[[], None]] = None,
    ):
        self.sample_rate = sample_rate
        self.on_next_stage_packet = on_next_stage_packet
        self.on_playback_finished = on_playback_finished

        self._lock = threading.Lock()
        self._stop_event = threading.Event()
        self._is_playing = False
        self._play_start_monotonic = 0.0
        self._total_duration_ms = 0
        self._current_char_records: List[Dict[str, Any]] = []
        self._current_expression: Optional[str] = None
        self._current_reply_text: str = ""
        self._request_seq = 0

    def is_playing(self) -> bool:
        return self._is_playing

    def stop(self) -> None:
        """毫秒级立即中断当前语音播报并闭嘴归中"""
        self._stop_event.set()
        if HAS_SD:
            try:
                sd.stop()
            except Exception:
                pass
        self._is_playing = False

    def speak_with_lip_sync(
        self,
        reply_text: str,
        expression: Optional[str],
        gaze_mode: str = "track_face",
        blocking: bool = False
    ) -> Dict[str, Any]:
        """
        1. 合成 reply_text 的 16kHz PCM 音频
        2. 计算每个字的平均振幅 char_amplitudes
        3. 将【表情词汇 + 每个字平均振幅表 + 动作意图】构造为下一级数据包并立即推送
        4. 启动音频播放，播放期间实时通过 get_live_state() 提供当前发音字与张嘴幅度
        """
        self.stop()
        self._request_seq += 1
        req_id = f"llm-{int(time.time() * 1000)}-{self._request_seq}"

        # 严格校验表情词汇只允许 "笑"、"难过" 或 None
        valid_expr = expression if expression in config.ALLOWED_EXPRESSIONS else None

        pcm = synthesize_tts_pcm(reply_text, self.sample_rate)
        char_amplitudes = compute_per_character_amplitudes(reply_text, pcm, self.sample_rate)
        duration_ms = int(round(len(pcm) * 1000.0 / self.sample_rate)) if pcm.size > 0 else (
            char_amplitudes[-1]["end_ms"] if char_amplitudes else 0
        )

        # 构造发送给下一级（NH21 21路调度器 & 外部消费者）的标准数据包
        # 同时兼容队友 examples/expression_intent.example.json 契约与逐字平均振幅扩展
        expr_id_map = {"笑": "smile", "难过": "sad", None: "neutral"}
        next_stage_packet = {
            "schema_version": 1,
            "request_id": req_id,
            "timestamp_epoch": round(time.time(), 3),
            "source": "qwen3.5:4b",
            "reply_text": reply_text,
            "expression_word": valid_expr if valid_expr is not None else "无",
            "expression": {
                "id": expr_id_map.get(valid_expr, "neutral"),
                "word": valid_expr,  # 仅 "笑" / "难过" / None
                "intensity": 0.85 if valid_expr is not None else 0.0,
            },
            "duration_ms": duration_ms,
            "ttl_ms": max(2000, duration_ms + 800),
            "gaze": {
                "mode": gaze_mode
            },
            "char_count": len(char_amplitudes),
            "char_amplitudes": char_amplitudes,
        }

        with self._lock:
            self._current_char_records = char_amplitudes
            self._current_expression = valid_expr
            self._current_reply_text = reply_text
            self._total_duration_ms = duration_ms

        # 立即通知下一级（NH21 调度器与 JSONL 记录器）
        if self.on_next_stage_packet:
            try:
                self.on_next_stage_packet(next_stage_packet)
            except Exception as e:
                print(f"[TTSLipSyncEngine] 推送下一级数据包异常: {e}")

        if pcm.size > 0:
            self._stop_event.clear()
            if blocking:
                self._playback_worker(pcm, duration_ms)
            else:
                threading.Thread(
                    target=self._playback_worker,
                    args=(pcm, duration_ms),
                    daemon=True,
                    name="TTSLipSyncPlayWorker"
                ).start()

        return next_stage_packet

    def _playback_worker(self, pcm: np.ndarray, duration_ms: int) -> None:
        self._is_playing = True
        self._play_start_monotonic = time.monotonic()
        try:
            if HAS_SD:
                sd.play(pcm, samplerate=self.sample_rate, blocking=False)
                while not self._stop_event.is_set():
                    elapsed_ms = (time.monotonic() - self._play_start_monotonic) * 1000.0
                    if elapsed_ms >= duration_ms + 40:
                        break
                    time.sleep(0.015)
                if self._stop_event.is_set():
                    sd.stop()
            else:
                # 无声卡输出设备时按真实时长模拟播放游标推进
                while not self._stop_event.is_set():
                    elapsed_ms = (time.monotonic() - self._play_start_monotonic) * 1000.0
                    if elapsed_ms >= duration_ms:
                        break
                    time.sleep(0.02)
        except Exception as e:
            print(f"[TTSLipSyncEngine] 音频播放异常: {e}")
        finally:
            self._is_playing = False
            if self.on_playback_finished:
                try:
                    self.on_playback_finished()
                except Exception:
                    pass

    def get_live_state(self) -> Dict[str, Any]:
        """
        供 20Hz NH21 调度器与 GUI 实时查询当前时刻正在发音的【字】及其【平均振幅 / 张嘴脉宽】
        """
        jaw_neutral = int(config.FACE_CHANNEL_CONFIG["jaw_mouth"]["neutral_us"])
        with self._lock:
            records = self._current_char_records
            expr = self._current_expression
            playing = self._is_playing
            t_start = self._play_start_monotonic
            total_ms = self._total_duration_ms

        if not playing or not records:
            return {
                "is_playing": False,
                "elapsed_ms": 0,
                "total_ms": total_ms,
                "expression_word": expr if expr is not None else "无",
                "active_char_index": -1,
                "active_char": "",
                "active_avg_amplitude": 0.0,
                "active_norm_amplitude": 0.0,
                "jaw_pulse_us": jaw_neutral,
            }

        elapsed_ms = int((time.monotonic() - t_start) * 1000.0)
        active_rec = None
        for rec in records:
            if rec["start_ms"] <= elapsed_ms <= rec["end_ms"]:
                active_rec = rec
                break

        if active_rec is None:
            # 处于句间标点停顿静音段：自然合拢嘴巴回中
            return {
                "is_playing": True,
                "elapsed_ms": elapsed_ms,
                "total_ms": total_ms,
                "expression_word": expr if expr is not None else "无",
                "active_char_index": -1,
                "active_char": "(停顿)",
                "active_avg_amplitude": 0.0,
                "active_norm_amplitude": 0.0,
                "jaw_pulse_us": jaw_neutral,
            }

        return {
            "is_playing": True,
            "elapsed_ms": elapsed_ms,
            "total_ms": total_ms,
            "expression_word": expr if expr is not None else "无",
            "active_char_index": active_rec["index"],
            "active_char": active_rec["char"],
            "active_avg_amplitude": active_rec["avg_amplitude"],
            "active_norm_amplitude": active_rec["norm_amplitude"],
            "jaw_pulse_us": active_rec["jaw_pulse_us"],
        }
