"""Operator starts the bounded physical trial locally; preview never sends UDP."""
from datetime import datetime
import hashlib
import json
from pathlib import Path
import queue
import threading
import time
import tkinter as tk
from tkinter import ttk

from nudge_eye_horizontal import ROOT
from requalify_eye import SETUP
import vision_eye_trial as trial


class VisionTrialPanel:
    def __init__(self,parent):
        self.window=tk.Toplevel(parent)
        self.window.title('NeuroHead 实物视觉响应 | 仅眼睛左右')
        self.window.geometry('840x600')
        self.window.minsize(820,580)
        self.thread=None;self.cancel=threading.Event();self.messages=queue.SimpleQueue()
        self.started=0.;self.closed=False
        self.confirm=tk.BooleanVar(value=False)
        self.preview=tk.StringVar(value='正在读取当前摄像头/ViSP数据…')
        self.status=tk.StringVar(value='预览中：未发送任何动作。')
        b=ttk.Frame(self.window,padding=18);b.pack(fill='both',expand=True)
        ttk.Label(b,text='真实眼睛 · 本机开始10秒演示',font=('Microsoft YaHei UI',18,'bold')).pack(anchor='w')
        ttk.Label(b,text='仅1495 / 1500 / 1505 μs三个位置；另一通道固定1500 μs。\n'
                  '动作幅度很小；模型方向与真实眼睛方向尚未标定。').pack(anchor='w',pady=10)
        self.preview_label=ttk.Label(b,textvariable=self.preview,font=('Microsoft YaHei UI',14),wraplength=740)
        self.preview_label.pack(anchor='w',pady=12)
        ttk.Label(b,text='先移动人脸，让下方文字出现两侧方向；预览不会驱动舵机。\n'
                  '准备好后点击开始，在10秒内缓慢移向左右两侧。').pack(anchor='w',pady=5)
        ttk.Checkbutton(b,text='我确认仅这只MG90S接通、4.8 V CV、中位稳定，并能现场断电',
                        variable=self.confirm).pack(anchor='w',pady=10)
        buttons=ttk.Frame(b);buttons.pack(fill='x',pady=8)
        self.start_button=ttk.Button(buttons,text='开始10秒（真实舵机会动）',command=self.start)
        self.start_button.pack(side='left',padx=(0,12))
        ttk.Button(buttons,text='停止发送（不切电）',command=self.cancel.set).pack(side='left')
        ttk.Label(b,textvariable=self.status,wraplength=740,foreground='#a52b22').pack(anchor='w',pady=12)
        ttk.Label(b,text='顶住、持续嗡鸣或异常时，立即关闭外部舵机电源。').pack(anchor='w')
        self.window.protocol('WM_DELETE_WINDOW',self.close)
        self.window.after(50,self.tick)

    def current(self):
        for p in sorted((ROOT/'data/pybullet_runs').glob('*/frames.jsonl'),
                        key=lambda p:p.stat().st_mtime,reverse=True):
            if time.time()-p.stat().st_mtime>3:continue
            row=trial.latest(p)
            if row.get('mode')=='vision_board':
                pulse=trial.visual_pulse(row,row['vision']['source_session_id'],time.monotonic())
                return p,row,pulse
        raise RuntimeError('没有新鲜的真实摄像头＋原生ViSP工作台数据')

    def start(self):
        if self.thread and self.thread.is_alive():return
        if not self.confirm.get():
            self.status.set('请先核对并勾选现场供电、单只舵机和中位条件。');return
        try:
            path,row,_=self.current()
            if row['vision'].get('target') is None:
                raise RuntimeError('未检测到人脸，请先让人脸框出现。')
            now=time.time()
            a=dict(authority='current_operator',created_at_epoch=now,expires_at_epoch=now+120,
                setup_sha256=hashlib.sha256(SETUP.read_bytes()).hexdigest(),offset_us=5,
                loaded_neutral_stable=True,supply_cv=True,single_servo_only=True,operator_ready=True,
                viewer_log=str(path),camera_session_id=row['vision']['source_session_id'],
                source='operator_local_button_and_physical_confirmation_checkbox',
                scope='One ten-second three-position visual response; global inhibit retained.')
            trial.VisionTrialSocket(None,a).check()
            folder=ROOT/'data/joint_runs'/f'{datetime.now():%Y%m%d_%H%M%S_%f}_local_vision_trial'
            folder.mkdir(parents=True)
            session=folder/'session.json'
            session.write_text(json.dumps(a,ensure_ascii=False,indent=2),encoding='utf-8')
        except (OSError,ValueError,RuntimeError,KeyError) as exc:
            self.status.set('未开始：'+str(exc));return
        self.cancel.clear();self.started=time.monotonic()
        self.start_button.configure(state='disabled')
        def work():
            try:
                result=trial.execute(session,cancel=self.cancel)
                points=sorted({x['pulse_us'] for x in result['source_inputs']})
                self.messages.put(f"已结束，数字检查{result['digital_checks_passed']}；请求位置{points} μs。\n"
                    f"{result.get('error') or '回读已恢复1500 μs；实际动作请现场确认。'}\n记录：{folder}")
            except Exception as exc:self.messages.put('测试未完成：'+str(exc))
        self.thread=threading.Thread(target=work,daemon=True);self.thread.start()

    def tick(self):
        if self.closed:return
        try:
            _,row,pulse=self.current()
            x=row['vision']['target'][0] if row['vision'].get('target') else None
            direction={1495:'模型负向',1500:'中位／无人脸',1505:'模型正向'}[pulse]
            self.preview.set(f'人脸中心x：{x:+.2f}\n{direction} → 候选脉宽 {pulse} μs' if x is not None
                             else '未检测到人脸 → 中位1500 μs')
        except Exception as exc:self.preview.set('预览不可用：'+str(exc))
        active=self.thread is not None and self.thread.is_alive()
        if active:self.status.set(f'实物测试运行中，已过 {time.monotonic()-self.started:.1f} 秒；结束后查询回中。')
        try:
            while True:self.status.set(self.messages.get_nowait())
        except queue.Empty:pass
        self.start_button.configure(state='disabled' if active else 'normal')
        self.window.after(150,self.tick)

    def close(self):
        self.closed=True;self.cancel.set();self.window.destroy()
