#!/usr/bin/env python3
"""Local single-joint panel. Simulation default; board query-only unless explicitly enabled."""
import argparse
from collections import deque
from datetime import datetime
import json
import time
import tkinter as tk
from tkinter import messagebox, ttk

from calibration_controller import CalibrationController, ROOT
from calibration_sequence import CalibrationSequence
import assembly_record


class CalibrationPanel:
    def __init__(self, root, mode='sim', enable_board_motion=False):
        self.root = root
        self.client = CalibrationController(mode, enable_board_motion=enable_board_motion)
        self.sequence = CalibrationSequence(self.client)
        self.sequence_number = 0
        self.sequence_reported = True
        self.points = deque(maxlen=180)
        self.closed = False
        self.vision_trial_panel = None
        self.joint = tk.StringVar(value='eye_horizontal')
        self.target = tk.StringVar(value='1500')
        self.step = tk.StringVar(value='5')
        self.hold = tk.StringVar(value='5')
        self.outcome = tk.StringVar(value='未观察 / 未验证')
        self.note = tk.StringVar()
        self.candidates = {key: tk.StringVar(value='1500') for key in ('min_us','center_us','max_us')}
        self.status = tk.StringVar(value='正在等待遥测…')
        self.readback = tk.StringVar(value='无数据')
        self.gate = tk.StringVar()
        self.action_text = tk.StringVar(value='尚未发送动作')
        self.save_text = tk.StringVar(value='保存的是未验证草稿，不修改板卡参数或解除故障禁用。')
        self.run_dir = ROOT/'data/calibration_runs'/f"{datetime.now():%Y%m%d_%H%M%S_%f}_{mode}"
        self.run_dir.mkdir(parents=True, exist_ok=True)
        self.telemetry = (self.run_dir/'telemetry.jsonl').open('w', encoding='utf-8')
        (self.run_dir/'manifest.json').write_text(json.dumps(dict(
            mode=mode, endpoint=self.client.peer, interface_index=self.client.interface_index,
            enable_board_motion=enable_board_motion,
            units='integer_microseconds', watchdog_pulse_us=1500,
            evidence='simulation_only' if mode=='sim' else 'register_readback_not_measured_angle',
            upstream_code_executed=False), indent=2), encoding='utf-8')
        root.title('NeuroHead 本地关节标定 v2 | '+('模拟' if mode=='sim' else '板卡监测'))
        root.geometry('1060x800')
        root.minsize(960, 700)
        body = ttk.Frame(root, padding=16)
        body.pack(fill='both', expand=True)
        body.columnconfigure(0, weight=1)
        title = '模拟模式：无实体舵机' if mode=='sim' else 'AX7020：真实板卡状态监测'
        ttk.Label(body, text=title, font=('Microsoft YaHei UI', 17, 'bold')).grid(row=0, sticky='w')
        ttk.Label(body, textvariable=self.status).grid(row=1, sticky='w', pady=4)
        tk.Label(body, textvariable=self.gate, fg='#a52b22', anchor='w', wraplength=990,
                 justify='left').grid(row=2, sticky='ew', pady=4)
        selection = ttk.Frame(body)
        selection.grid(row=3, sticky='ew', pady=5)
        ttk.Label(selection, text='当前关节').pack(side='left')
        self.selector = ttk.Combobox(selection, textvariable=self.joint, state='readonly',
                                     values=list(self.client.profiles), width=23)
        self.selector.pack(side='left', padx=8)
        self.joint_label = ttk.Label(selection)
        self.joint_label.pack(side='left')
        self.selector.bind('<<ComboboxSelected>>', self.select_joint)
        ttk.Label(body, textvariable=self.readback, font=('Consolas', 12)).grid(row=4, sticky='w', pady=5)
        ttk.Label(body, text='显示的是PL脉宽设置，不是实测角度；本系统目前没有电流/位置反馈。').grid(row=5, sticky='w')
        control = ttk.LabelFrame(body, text='本地动作操作（每次准备2秒，定时停止发送）', padding=10)
        control.grid(row=6, sticky='ew', pady=8)
        ttk.Label(control, text='目标 / μs').grid(row=0, column=0)
        ttk.Entry(control, textvariable=self.target, width=8).grid(row=0, column=1, padx=6)
        ttk.Label(control, text='步长 / μs').grid(row=0, column=2)
        ttk.Combobox(control, textvariable=self.step, values=(1,5,10,25), state='readonly', width=5).grid(row=0, column=3, padx=6)
        ttk.Button(control, text='－', width=4, command=lambda:self.adjust(-1)).grid(row=0, column=4, padx=3)
        ttk.Button(control, text='＋', width=4, command=lambda:self.adjust(1)).grid(row=0, column=5, padx=3)
        ttk.Label(control, text='停留 / 秒').grid(row=0, column=6, padx=6)
        ttk.Combobox(control, textvariable=self.hold, values=(2,5), state='readonly', width=4).grid(row=0, column=7)
        self.execute = ttk.Button(control, text='执行一次', command=self.start_action)
        self.execute.grid(row=0, column=8, padx=12)
        tk.Button(control, text='停止发送（不切电）', bg='#a52b22', fg='white',
                  command=self.stop_action).grid(row=0, column=9, padx=6)
        ttk.Label(control, textvariable=self.action_text).grid(row=1, column=0, columnspan=10, sticky='w', pady=(8,0))
        self.demo = ttk.Button(control,text='模拟：往复三组（每点2秒）',command=self.start_demo)
        self.demo.grid(row=2,column=0,columnspan=4,sticky='w',pady=(8,0))
        self.export = ttk.Button(control,text='导出序列报告',command=self.export_sequence,state='disabled')
        self.export.grid(row=2,column=4,columnspan=4,sticky='w',pady=(8,0))
        ttk.Label(body, text='停止、网络中断或关闭窗口后，依赖板上看门狗回1500 μs；不会切断舵机电源。').grid(row=7, sticky='w')
        self.plot = tk.Canvas(body, height=125, background='#152538', highlightthickness=0)
        self.plot.grid(row=8, sticky='nsew', pady=8)
        body.rowconfigure(8, weight=1)
        ttk.Label(body, text='青色曲线：所选通道的PL输出设置；不是示波器波形。').grid(row=9, sticky='w')
        draft = ttk.LabelFrame(body, text='标定记录草稿（不会自动变为已验证范围）', padding=10)
        draft.grid(row=10, sticky='ew', pady=8)
        for col, (key, label) in enumerate((('min_us','低脉宽候选'),('center_us','中位候选'),('max_us','高脉宽候选'))):
            ttk.Label(draft, text=label+' / μs').grid(row=0, column=col*2, padx=3)
            ttk.Entry(draft, textvariable=self.candidates[key], width=8).grid(row=0, column=col*2+1, padx=4)
        ttk.Button(draft, text='保存草稿', command=self.save_draft).grid(row=0, column=6, padx=12)
        ttk.Button(draft, text='装配与接线记录…', command=self.open_assembly).grid(
            row=2, column=0, columnspan=3, sticky='w', pady=(4,0))
        self.vision_trial_button=ttk.Button(draft,text='实物视觉响应10秒…',command=self.open_vision_trial,
            state='normal' if mode=='board' else 'disabled')
        self.vision_trial_button.grid(row=2,column=3,columnspan=4,sticky='w',pady=(4,0))
        ttk.Label(draft, text='现场观察').grid(row=1, column=0, pady=8)
        outcome = ttk.Combobox(draft, textvariable=self.outcome, state='readonly', width=23,
                              values=('未观察 / 未验证','移动并返回','未看到动作','顶住 / 异常，需断电'))
        outcome.grid(row=1, column=1, columnspan=2, sticky='w', padx=4)
        outcome.bind('<<ComboboxSelected>>', self.observation_changed)
        ttk.Label(draft, text='备注').grid(row=1, column=3)
        ttk.Entry(draft, textvariable=self.note, width=43).grid(row=1, column=4, columnspan=3, sticky='ew')
        ttk.Label(body, textvariable=self.save_text, wraplength=990).grid(row=11, sticky='w')
        ttk.Label(body, text=f'记录目录：{self.run_dir}', wraplength=990).grid(row=12, sticky='w', pady=(6,0))
        self.select_joint()
        root.protocol('WM_DELETE_WINDOW', self.close)
        root.after(25, self.tick)

    def open_vision_trial(self):
        if self.client.sim:return
        if self.vision_trial_panel and not self.vision_trial_panel.closed:
            self.vision_trial_panel.window.lift();return
        from vision_trial_panel import VisionTrialPanel
        self.vision_trial_panel=VisionTrialPanel(self.root)

    def open_assembly(self):
        if getattr(self, 'assembly_window', None) is not None and self.assembly_window.winfo_exists():
            self.assembly_window.lift()
            return
        joint = self.joint.get()
        profile = self.client.profiles[joint]
        win = self.assembly_window = tk.Toplevel(self.root)
        win.title('装配与接线记录 | '+profile['label'])
        win.geometry('780x580')
        win.minsize(760,560)
        box = ttk.Frame(win, padding=16)
        box.pack(fill='both', expand=True)
        box.columnconfigure(1, weight=1)
        ttk.Label(box, text=profile['label']+' · 现场装配记录',
                  font=('Microsoft YaHei UI',16,'bold')).grid(row=0,columnspan=2,sticky='w')
        ttk.Label(box, text=f"当前PL通道 {profile['channel']}；信号：J10第{profile['signal_pin']}针。",
                  padding=(0,8)).grid(row=1,columnspan=2,sticky='w')
        ttk.Label(box, text='眼睛左右：J10第1针为公共GND；舵机由独立外部电源供电。\n'
                  '针位对应当前原版AX7020工程；双眼左右使用同一驱动连杆。',
                  wraplength=710).grid(row=2,columnspan=2,sticky='w',pady=(0,10))
        self.assembly_fields = {}
        for row,(key,values) in enumerate(assembly_record.CHOICES.items(),start=3):
            value = self.assembly_fields[key] = tk.StringVar(value=values[0])
            ttk.Label(box,text=assembly_record.LABELS[key]).grid(row=row,column=0,sticky='w',pady=7,padx=(0,16))
            ttk.Combobox(box,textvariable=value,values=values,state='readonly',width=55).grid(
                row=row,column=1,sticky='ew')
        self.assembly_note = tk.StringVar()
        ttk.Label(box,text='现场备注').grid(row=8,column=0,sticky='w',pady=8)
        ttk.Entry(box,textvariable=self.assembly_note).grid(row=8,column=1,sticky='ew')
        snapshot = assembly_record.capture(self.client,joint,
            {k:v.get() for k,v in self.assembly_fields.items()})
        fault = snapshot['fault_snapshot']
        prior = ('当前档案：动作禁用；需复核装配零位。' if fault and fault.get('motion_inhibited')
                 else '当前档案状态请结合主窗口的动作限制查看。')
        ttk.Label(box,text=prior+'\n本页填写的是本次现场反馈；不会自动覆盖历史故障或安全范围。',
                  wraplength=710,foreground='#a52b22').grid(row=9,columnspan=2,sticky='w',pady=10)
        result = tk.StringVar(value='未填写的项目保持“未确认”；保存后仍由主窗口查询板卡。')
        ttk.Label(box,textvariable=result,wraplength=710).grid(row=11,columnspan=2,sticky='w',pady=10)
        def store():
            try:
                paths = assembly_record.save(self.client,joint,
                    {k:v.get() for k,v in self.assembly_fields.items()},self.assembly_note.get(),self.run_dir)
                result.set('已保存：'+str(paths[1]))
            except (OSError,ValueError) as exc:
                result.set('保存失败：'+str(exc))
        self.assembly_save = ttk.Button(box,text='保存本次装配记录',command=store)
        self.assembly_save.grid(row=10,columnspan=2,sticky='w')

    def select_joint(self, event=None):
        p = self.client.profiles[self.joint.get()]
        low, high = self.client.envelope(self.joint.get())
        self.joint_label.configure(text=f"{p['label']} | {p['channel']} | J10第{p['signal_pin']}针 | 会话范围 {low}..{high} μs")
        self.target.set('1500')
        self.points.clear()

    def adjust(self, sign):
        try:
            low, high = self.client.envelope(self.joint.get())
            value = int(self.target.get())+sign*int(self.step.get())
            self.target.set(str(max(low, min(high, value))))
        except ValueError:
            self.target.set('1500')

    def start_action(self):
        try:
            self.client.start(self.joint.get(), int(self.target.get()), int(self.hold.get()))
            self.sequence = CalibrationSequence(self.client)
            self.sequence_reported = True
        except (ValueError, OSError) as exc:
            messagebox.showerror('未发送动作', str(exc), parent=self.root)

    def stop_action(self):
        self.sequence.cancel()
        self.client.stop()

    def start_demo(self):
        try:
            self.sequence.start_demo(self.joint.get())
            self.sequence_number += 1
            self.sequence_reported = False
        except (ValueError,OSError) as exc:
            messagebox.showerror('未开始序列',str(exc),parent=self.root)

    def export_sequence(self):
        try:
            paths=self.sequence.export(self.run_dir,f'sequence_{self.sequence_number:04d}')
            self.save_text.set('已导出模拟报告：'+str(paths[1]))
            self.sequence_reported=True
            return paths
        except (OSError,ValueError) as exc:
            self.save_text.set('报告未导出：'+str(exc))

    def observation_changed(self, event=None):
        if not self.outcome.get().startswith('顶住'):
            return
        self.sequence.cancel('现场报告异常')
        self.client.stop('现场报告异常，请立即关闭舵机外部电源')
        if not self.client.sim:
            path = self.client.fault_dir/(self.joint.get()+'.json')
            try:
                state = json.loads(path.read_text(encoding='utf-8')) if path.exists() else {'joint':self.joint.get()}
                state.update(motion_inhibited=True, motion_inhibit_reason='Operator reported abnormality from local calibration panel')
                temp = path.with_suffix('.tmp')
                temp.write_text(json.dumps(state, indent=2, ensure_ascii=False), encoding='utf-8')
                temp.replace(path)
            except (OSError, ValueError, AttributeError) as exc:
                self.client.enable_board_motion = False
                self.save_text.set(f'故障标记保存失败，已禁用本窗口实体动作：{exc}')

    def save_draft(self):
        try:
            values = {k:int(v.get()) for k,v in self.candidates.items()}
            if not 600 <= values['min_us'] <= values['center_us'] <= values['max_us'] <= 2400:
                raise ValueError('候选值需为600..2400内的有序整数微秒；电气范围不代表机械安全。')
            out = ROOT/'data/calibration_drafts'
            out.mkdir(parents=True, exist_ok=True)
            path = out/f"{datetime.now():%Y%m%d_%H%M%S_%f}_{self.client.mode}_{self.joint.get()}.json"
            draft = dict(schema_version=1, joint=self.joint.get(), mode=self.client.mode,
                         candidate=values, range_verified=False, units='us',
                         observation=self.outcome.get(), operator_note=self.note.get(),
                         board_watchdog_pulse_us=1500, telemetry=self.client.state,
                         evidence='simulation_only' if self.client.sim else 'operator_observation_and_register_readback',
                         telemetry_run=str(self.run_dir.relative_to(ROOT)),
                         boundary='Draft only: does not alter runtime envelopes, fault state or board registers.')
            path.write_text(json.dumps(draft, indent=2, ensure_ascii=False), encoding='utf-8')
            self.save_text.set(f'已保存未验证草稿：{path.name}')
            return path
        except (OSError, ValueError) as exc:
            messagebox.showerror('无法保存草稿', str(exc), parent=self.root)

    def tick(self):
        if self.closed:
            return
        c = self.client
        try:
            c.tick()
            self.sequence.tick()
            if not self.sequence_reported and self.sequence.status in ('completed','aborted'):
                self.export_sequence()
            for row in c.samples:
                self.telemetry.write(json.dumps(row)+'\n')
            c.samples.clear()
            self.telemetry.flush()
            fresh = c.state is not None and time.monotonic()-c.last_rx < .4
            self.status.set(f"{'在线' if fresh else '等待遥测 / 链路中断'} | {c.mode.upper()} | UDP {c.peer[0]}:{c.peer[1]} | 已发送动作帧 {c.command_frames_sent}")
            try:
                reason = c.permission_reason(self.joint.get(), int(self.target.get()))
            except ValueError:
                reason = '目标必须为整数微秒'
            self.gate.set(('模拟范围仅用于演示，不是机械标定。' if c.sim else '实体操作门限：')+(reason or ' 可执行一次定时动作'))
            idle=c.phase=='idle' and not self.sequence.active
            self.execute.configure(state='normal' if not reason and idle else 'disabled')
            self.demo.configure(state='normal' if c.sim and idle and not c.permission_reason(self.joint.get(),1500) else 'disabled')
            self.export.configure(state='normal' if self.sequence.status in ('completed','aborted') else 'disabled')
            self.selector.configure(state='readonly' if idle else 'disabled')
            if c.state:
                s = c.state
                axis = c.profiles[self.joint.get()]['channel']
                self.readback.set(f"目标寄存器 {s['target_'+axis+'_us']} μs | 输出设置 {s['output_'+axis+'_us']} μs | 看门狗 {bool(s['status']&2)} | 拒绝 {s['invalid']}/{s['stale']}")
                self.points.append(s['output_'+axis+'_us'])
            if c.phase=='prepare':
                text = f"准备观察：{max(0,c.action['prepare_until']-time.monotonic()):.1f}秒后发送"
            elif c.phase=='hold':
                text = f"目标 {c.action['target']} μs，剩余 {max(0,c.action['end']-time.monotonic()):.1f}秒"
            elif c.phase=='return':
                text = '已停止命令，正在查询看门狗返回1500 μs'
            else:
                text = c.message
            if self.sequence.active:
                text=f'模拟序列 {self.sequence.index+1}/6 | '+text
            elif self.sequence.status=='completed':
                text='模拟三组往复完成，6步回读检查通过；'+('报告已保存' if self.sequence_reported else '报告导出待处理')
            elif self.sequence.status=='aborted':
                text='模拟序列已停止：'+self.sequence.reason+' | '+text
            self.action_text.set(text)
            self.draw()
        except (OSError, ValueError) as exc:
            self.sequence.cancel('通信/配置错误')
            c.stop('通信/配置错误')
            self.execute.configure(state='disabled')
            self.status.set(f'错误，已停止发送：{exc}')
        self.root.after(25, self.tick)

    def draw(self):
        c = self.plot
        c.delete('all')
        w,h = max(200,c.winfo_width()),max(80,c.winfo_height())
        low = min(1450, min(self.points, default=1500))-25
        high = max(1550, max(self.points, default=1500))+25
        for value in (low,1500,high):
            y = h-12-(value-low)/(high-low)*(h-24)
            c.create_line(48,y,w,y,fill='#42546b')
            c.create_text(25,y,text=str(value),fill='white')
        coords=[]
        for i,value in enumerate(self.points):
            coords.extend((50+i*(w-60)/179,h-12-(value-low)/(high-low)*(h-24)))
        if len(coords)>=4:
            c.create_line(*coords,fill='#4be2de',width=2)

    def close(self):
        if self.closed:
            return
        self.closed=True
        if self.vision_trial_panel and not self.vision_trial_panel.closed:
            self.vision_trial_panel.close()
        self.sequence.cancel('关闭窗口')
        if not self.sequence_reported and self.sequence.status in ('completed','aborted'):
            self.export_sequence()
        self.client.close()
        (self.run_dir/'events.json').write_text(json.dumps(self.client.events,indent=2,ensure_ascii=False),encoding='utf-8')
        self.telemetry.close()
        self.root.destroy()


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--mode',choices=('sim','board'),default='sim')
    p.add_argument('--enable-board-motion',action='store_true',help='still requires verified envelopes and no fault inhibit')
    p.add_argument('--demo',action='store_true',help='start a three-group demo automatically; simulation only')
    p.add_argument('--vision-trial',action='store_true',help='open bounded physical visual trial controls; does not auto-start')
    args=p.parse_args()
    if args.demo and args.mode!='sim':
        p.error('--demo is simulation-only; no board connection opened')
    if args.vision_trial and args.mode!='board':
        p.error('--vision-trial requires board read-only monitor mode')
    root=tk.Tk()
    try:
        panel=CalibrationPanel(root,args.mode,args.enable_board_motion)
    except (OSError,ValueError,KeyError) as exc:
        messagebox.showerror('标定面板启动失败',str(exc),parent=root)
        root.destroy()
        return
    if args.demo:
        root.after(1000,panel.start_demo)
    if args.vision_trial:
        root.after(500,panel.open_vision_trial)
    root.mainloop()


if __name__=='__main__':
    main()
