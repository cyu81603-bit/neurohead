"""
video_buffer.py - 常开视频采集与 5 秒动态滚动/语音全段锁定缓冲池
严格实现需求 2：
1. 视频常开，实时采集画面。
2. 系统静默状态（用户不说话）下，严格只保留 [now - 5.0s, now] 的视频帧，5 秒前的帧实时删除。
3. 用户说话时，从发出语音那一瞬间前 5 秒 (t_speech_start - 5.0s) 到结束说话 (t_speech_end) 的整段视频完整保留，
   抽样合成为带精确相对时序坐标的多模态视觉输入，送入 Qwen3.5:4b 大模型。
"""

import time
import base64
import threading
from collections import deque
from typing import Optional, List, Tuple, Dict, Any, Callable
import cv2
import numpy as np

import config


class TemporalVideoBuffer:
    """
    动态时序视频环形池：
    - 静默态 (SILENT_ROLLING_5S): 每次写入新帧时自动清除 timestamp < now - 5.0s 的旧帧。
    - 说话态 (SPEECH_LOCKED): 锁定裁剪起点为 t_speech_start - 5.0s，持续累积至 t_speech_end。
    """

    def __init__(
        self,
        silent_retention_s: float = config.SILENT_RETENTION_SECONDS,
        pre_speech_lookback_s: float = config.PRE_SPEECH_LOOKBACK_SECONDS,
        num_vlm_frames: int = config.VLM_STORYBOARD_FRAMES
    ):
        self.silent_retention_s = float(silent_retention_s)
        self.pre_speech_lookback_s = float(pre_speech_lookback_s)
        self.num_vlm_frames = int(num_vlm_frames)

        self._lock = threading.Lock()
        self._frames: deque[Tuple[float, np.ndarray]] = deque()
        self._speech_start_ts: Optional[float] = None
        self._latest_frame: Optional[np.ndarray] = None
        self._latest_ts: float = 0.0
        self._last_extracted_storyboard: Optional[np.ndarray] = None
        self._last_segment_info: Dict[str, Any] = {}

    def push_frame(self, frame_bgr: np.ndarray, timestamp_s: Optional[float] = None) -> None:
        """
        推入一帧新画面并执行动态过期清理：
        - 若当前未说话：立即删除 (now - 5.0s) 之前的全部视频帧
        - 若当前正在说话：锁定保留 (t_speech_start - 5.0s) 之后的全部视频帧
        """
        if frame_bgr is None:
            return
        now_ts = float(timestamp_s) if timestamp_s is not None else time.monotonic()
        frame_copy = frame_bgr.copy()

        with self._lock:
            self._frames.append((now_ts, frame_copy))
            self._latest_frame = frame_copy
            self._latest_ts = now_ts
            self._prune_unlocked(now_ts)

    def _prune_unlocked(self, now_ts: float) -> None:
        if self._speech_start_ts is not None:
            # 说话期间：保留发出语音瞬间前 5 秒至今的所有帧
            cutoff_ts = self._speech_start_ts - self.pre_speech_lookback_s
        else:
            # 静默状态：只保留最近 5 秒，5 秒前的立即删除
            cutoff_ts = now_ts - self.silent_retention_s

        while self._frames and self._frames[0][0] < cutoff_ts:
            self._frames.popleft()

    def on_speech_start(self, t_speech_start: Optional[float] = None) -> None:
        """
        当检测到用户开始说话瞬间调用，锁定缓冲池起点为 [t_speech_start - 5.0s]
        """
        with self._lock:
            if t_speech_start is None:
                t_speech_start = self._latest_ts if self._latest_ts > 0 else time.monotonic()
            self._speech_start_ts = float(t_speech_start)
            self._prune_unlocked(self._latest_ts if self._latest_ts > 0 else self._speech_start_ts)

    def on_speech_cancel(self) -> None:
        """
        语音被过滤或取消时解除说话锁定，恢复 5 秒静默滚动清理
        """
        with self._lock:
            self._speech_start_ts = None
            if self._latest_ts > 0:
                self._prune_unlocked(self._latest_ts)

    def extract_speech_video(
        self,
        t_speech_start: float,
        t_speech_end: float
    ) -> Dict[str, Any]:
        """
        当用户结束说话时调用：
        1. 提取 [t_speech_start - 5.0s, t_speech_end] 的全部视频帧
        2. 解除说话锁定，将缓冲池恢复为保留最近 5 秒的静默滚动状态
        3. 生成供 Qwen3.5:4b 视觉理解的时序关键帧序列与 Base64 图像
        """
        target_start = float(t_speech_start) - self.pre_speech_lookback_s
        target_end = float(t_speech_end)

        with self._lock:
            segment = [
                (ts, frm) for (ts, frm) in self._frames
                if (ts >= target_start - 0.05 and ts <= target_end + 0.10)
            ]
            if not segment and self._frames:
                segment = list(self._frames)

            # 解除说话锁定并立即清理超过 5 秒的旧帧
            self._speech_start_ts = None
            now_ref = max(target_end, self._latest_ts)
            self._prune_unlocked(now_ref)

        if not segment:
            return {
                "valid": False,
                "frame_count": 0,
                "span_seconds": 0.0,
                "pre_speech_seconds": 0.0,
                "speaking_seconds": 0.0,
                "storyboard_bgr": None,
                "storyboard_b64": None,
                "sampled_frames": [],
            }

        actual_start = segment[0][0]
        actual_end = segment[-1][0]
        total_span = max(0.0, actual_end - actual_start)
        pre_span = max(0.0, float(t_speech_start) - actual_start)
        speak_span = max(0.0, actual_end - float(t_speech_start))

        # 均匀抽样 N 帧代表从 [说话前5秒] 到 [说话结束] 的完整时序演变
        n_total = len(segment)
        k = min(self.num_vlm_frames, n_total)
        indices = np.linspace(0, n_total - 1, k, dtype=int)
        sampled = [segment[idx] for idx in indices]

        storyboard_bgr = self._build_storyboard(sampled, float(t_speech_start))
        storyboard_b64 = self.encode_bgr_to_base64(storyboard_bgr, max_dim=540)

        info = {
            "valid": True,
            "frame_count": n_total,
            "span_seconds": round(total_span, 2),
            "pre_speech_seconds": round(pre_span, 2),
            "speaking_seconds": round(speak_span, 2),
            "t_window_start": actual_start,
            "t_speech_start": float(t_speech_start),
            "t_speech_end": actual_end,
            "storyboard_bgr": storyboard_bgr,
            "storyboard_b64": storyboard_b64,
            "sampled_frames": sampled,
        }
        with self._lock:
            self._last_extracted_storyboard = storyboard_bgr
            self._last_segment_info = info
        return info

    def _build_storyboard(
        self,
        sampled: List[Tuple[float, np.ndarray]],
        t_speech_start: float
    ) -> np.ndarray:
        """
        将抽样的时序帧拼接为 3x2 (或 2x2) 故事板，并在每格标注相对于开口时刻的时间戳
        例如: "-4.9s [Pre-Speech]", "-2.4s [Pre-Speech]", "+0.0s [Speak Start]", "+1.2s [Speaking]"
        """
        tw, th = config.VLM_GRID_TILE_W, config.VLM_GRID_TILE_H
        tiles = []
        for idx, (ts, frm) in enumerate(sampled):
            resized = cv2.resize(frm, (tw, th), interpolation=cv2.INTER_AREA)
            rel_t = ts - t_speech_start
            if rel_t < -0.15:
                phase_tag = "Pre-5s"
                col = (255, 200, 0)   # 蓝青色表示说话前5秒回溯阶段
            elif abs(rel_t) <= 0.25:
                phase_tag = "Start"
                col = (0, 255, 255)   # 黄色表示开口瞬间
            else:
                phase_tag = "Speak"
                col = (0, 255, 100)   # 绿色表示说话期间

            # 绘制顶部半透明标签底栏
            overlay = resized.copy()
            cv2.rectangle(overlay, (0, 0), (tw, 26), (15, 15, 15), -1)
            cv2.addWeighted(overlay, 0.72, resized, 0.28, 0, resized)
            label = f"#{idx+1} {rel_t:+.1f}s [{phase_tag}]"
            cv2.putText(resized, label, (6, 18), cv2.FONT_HERSHEY_SIMPLEX, 0.48, col, 1, cv2.LINE_AA)
            cv2.rectangle(resized, (0, 0), (tw - 1, th - 1), col, 1)
            tiles.append(resized)

        # 补齐到偶数格便于网格拼接
        while len(tiles) < 6 and len(tiles) not in (1, 2, 4):
            tiles.append(np.zeros((th, tw, 3), dtype=np.uint8))

        if len(tiles) >= 6:
            row1 = np.hstack(tiles[0:3])
            row2 = np.hstack(tiles[3:6])
            return np.vstack([row1, row2])
        elif len(tiles) == 4:
            row1 = np.hstack(tiles[0:2])
            row2 = np.hstack(tiles[2:4])
            return np.vstack([row1, row2])
        elif len(tiles) == 2:
            return np.hstack(tiles)
        return tiles[0]

    @staticmethod
    def encode_bgr_to_base64(image_bgr: Optional[np.ndarray], max_dim: int = 540) -> Optional[str]:
        if image_bgr is None:
            return None
        try:
            h, w = image_bgr.shape[:2]
            scale = min(1.0, float(max_dim) / float(max(h, w)))
            if scale < 1.0:
                image_bgr = cv2.resize(
                    image_bgr,
                    (max(1, int(w * scale)), max(1, int(h * scale))),
                    interpolation=cv2.INTER_AREA
                )
            ok, buf = cv2.imencode(".jpg", image_bgr, [cv2.IMWRITE_JPEG_QUALITY, 78])
            if not ok:
                return None
            return base64.b64encode(buf).decode("utf-8")
        except Exception:
            return None

    def get_latest_frame(self) -> Tuple[Optional[np.ndarray], float]:
        with self._lock:
            if self._latest_frame is None:
                return None, 0.0
            return self._latest_frame.copy(), self._latest_ts

    def get_status(self) -> Dict[str, Any]:
        """返回当前视频池实时状态供 GUI 与监控展示"""
        with self._lock:
            n = len(self._frames)
            if n >= 2:
                oldest_ts = self._frames[0][0]
                newest_ts = self._frames[-1][0]
                span_s = max(0.0, newest_ts - oldest_ts)
            else:
                oldest_ts = 0.0
                newest_ts = 0.0
                span_s = 0.0
            is_locked = self._speech_start_ts is not None
            return {
                "mode": "SPEECH_LOCKED" if is_locked else "SILENT_ROLLING_5S",
                "frame_count": n,
                "span_seconds": round(span_s, 2),
                "speech_start_ts": self._speech_start_ts,
                "oldest_ts": oldest_ts,
                "newest_ts": newest_ts,
                "last_segment_info": self._last_segment_info,
            }


class AlwaysOnCameraHub:
    """
    单例常开相机中枢：
    - 遵照队友文档“同一 USB Cam 不重复打开”原则，全局唯一打开摄像头。
    - 每帧同时分发给：
      1) TemporalVideoBuffer (静默保留5s / 说话截取前5s至结束)
      2) 外部注册的观察者回调 (如队友的 YuNet 人脸追踪与 SceneMotion 模块)
    """

    def __init__(
        self,
        video_buffer: TemporalVideoBuffer,
        camera_index: int = config.CAMERA_INDEX,
        width: int = config.FRAME_WIDTH,
        height: int = config.FRAME_HEIGHT,
        fps: int = config.CAMERA_FPS
    ):
        self.video_buffer = video_buffer
        self.camera_index = camera_index
        self.width = width
        self.height = height
        self.fps = fps

        self.is_running = False
        self.using_synthetic = False
        self.actual_fps = 0.0
        self._cap = None
        self._thread: Optional[threading.Thread] = None
        self._callbacks: List[Callable[[np.ndarray, int, float], None]] = []
        self._frame_id = 0

    def register_frame_callback(self, cb: Callable[[np.ndarray, int, float], None]) -> None:
        self._callbacks.append(cb)

    def start(self) -> "AlwaysOnCameraHub":
        if self.is_running:
            return self
        self.is_running = True
        self._thread = threading.Thread(target=self._capture_loop, daemon=True, name="AlwaysOnCameraHub")
        self._thread.start()
        return self

    def stop(self) -> None:
        self.is_running = False
        if self._thread is not None:
            self._thread.join(timeout=1.5)
        if self._cap is not None:
            try:
                self._cap.release()
            except Exception:
                pass
            self._cap = None

    def _open_camera(self):
        # 优先尝试 DirectShow 打开物理相机
        for backend in (cv2.CAP_DSHOW, cv2.CAP_MSMF, cv2.CAP_ANY):
            try:
                cap = cv2.VideoCapture(self.camera_index, backend)
                if cap is not None and cap.isOpened():
                    cap.set(cv2.CAP_PROP_FRAME_WIDTH, self.width)
                    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, self.height)
                    cap.set(cv2.CAP_PROP_FPS, self.fps)
                    cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
                    ret, frm = cap.read()
                    if ret and frm is not None:
                        self.using_synthetic = False
                        return cap
                    cap.release()
            except Exception:
                pass
        self.using_synthetic = True
        return None

    def _generate_synthetic_frame(self, now_ts: float) -> np.ndarray:
        """当无物理摄像头连接时，生成带平滑移动仿真人脸的测试帧，确保离线测试可完整运行"""
        frm = np.full((self.height, self.width, 3), 28, dtype=np.uint8)
        cx = int(self.width * 0.5 + 80 * np.sin(now_ts * 0.8))
        cy = int(self.height * 0.5 + 40 * np.cos(now_ts * 0.6))
        cv2.circle(frm, (cx, cy), 55, (180, 200, 230), -1)
        cv2.circle(frm, (cx - 20, cy - 12), 7, (40, 40, 40), -1)
        cv2.circle(frm, (cx + 20, cy - 12), 7, (40, 40, 40), -1)
        cv2.ellipse(frm, (cx, cy + 16), (22, 10), 0, 0, 180, (60, 60, 180), 3)
        cv2.putText(
            frm, f"SIMULATED CAM | t={now_ts:.1f}s", (15, 30),
            cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 220, 255), 2
        )
        return frm

    def _capture_loop(self) -> None:
        self._cap = self._open_camera()
        fps_cnt = 0
        fps_t0 = time.monotonic()
        target_dt = 1.0 / max(1, self.fps)

        while self.is_running:
            t_loop = time.monotonic()
            frm = None
            if self._cap is not None:
                ret, read_frm = self._cap.read()
                if ret and read_frm is not None:
                    frm = read_frm
                else:
                    time.sleep(0.01)
                    continue
            else:
                frm = self._generate_synthetic_frame(t_loop)

            now_ts = time.monotonic()
            self._frame_id += 1
            self.video_buffer.push_frame(frm, now_ts)

            for cb in self._callbacks:
                try:
                    cb(frm, self._frame_id, now_ts)
                except Exception:
                    pass

            fps_cnt += 1
            if now_ts - fps_t0 >= 0.5:
                self.actual_fps = fps_cnt / (now_ts - fps_t0)
                fps_cnt = 0
                fps_t0 = now_ts

            elapsed = time.monotonic() - t_loop
            if self.using_synthetic and elapsed < target_dt:
                time.sleep(target_dt - elapsed)
            elif not self.using_synthetic:
                time.sleep(0.002)
