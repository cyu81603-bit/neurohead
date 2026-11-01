"""Frontal gaze, verified facial actions and local speech-file playback."""
import argparse,copy,json,os,queue,time,uuid,tkinter as tk
from tkinter import ttk,filedialog
from pathlib import Path
import head_follow_panel as head_ui
from lifelike_control import LifelikeSession
from speech_audio import AudioPlayer
from lifelike_api import IntentServer
from runtime_logs import write_status
ROOT=Path(__file__).resolve().parents[2];CONFIG=ROOT/'config/lifelike_v6.json'
class LifelikePanel(head_ui.Panel):
    def __init__(self,window,controller_factory=LifelikeSession):
        self.life_config=json.loads(CONFIG.read_text(encoding='utf-8'));self.events=queue.Queue();self.api=None
        def factory(profile):return controller_factory(dict(profile,lifelike=self.life_config,prefer_frontal=self.life_config.get('prefer_frontal',True),frontal_response=self.life_config.get('frontal_response',{}),neck_tracking_rate_us_per_s=self.life_config.get('neck_tracking_rate_us_per_s',[20,15]),neck_tracking_gain=self.life_config.get('neck_tracking_gain',.35)))
        super().__init__(window,controller_factory=factory);window.title('NeuroHead v6.3 · 表情不重置追踪 · Vivado2026')
        self.audio=AudioPlayer(self.control,lambda kind,text:self.events.put((kind,text)))
        self.life_window=tk.Toplevel(window);w=self.life_window;w.title('NeuroHead v6.3 · MG995下颚两点开合');w.geometry('1100x920')
        tk.Label(w,text='眉舒展 · 自然眨眼 · 语音嘴形 · 正面朝向',font=('Microsoft YaHei UI',18,'bold')).pack(pady=8)
        blocked=[p['label'] for p in self.life_config['poses'] if p.get('automatic_inhibited') is True]
        if blocked:tk.Label(w,text='自动输出已屏蔽：'+ '、'.join(blocked)+'；仅保留显式单路手动预览。',fg='#9b3e00').pack()
        self.session_text=tk.StringVar(master=w,value='本窗口会话未启动')
        tk.Label(w,textvariable=self.session_text,font=('Microsoft YaHei UI',11)).pack(pady=4)
        row=tk.Frame(w);row.pack()
        tk.Checkbutton(row,text='已确认接线/外部供电/共地，头部托稳',variable=self.ready).pack(side='left')
        tk.Button(row,text='打开／复用USB Cam预览',command=self.open_camera).pack(side='left',padx=5)
        tk.Button(row,text='开始本窗口会话',command=self.start).pack(side='left',padx=8)
        tk.Button(row,text='已托稳，结束全部PWM',command=self.end).pack(side='left',padx=8)
        tk.Label(w,text='下颚使用独立手动调节条；不受25μs步长或说话范围限制。上表范围用于自动表情。').pack(pady=5)
        jaw=self.life_config.get('jaw_setup')
        if jaw:
            text=f"{jaw.get('model','下颚')}：已观察闭嘴{jaw['closed_us']}μs → 张嘴{jaw['observed_open_us']}μs；两点切换随语音开合；自动行程仅在这两个端点之间。" if jaw.get('operator_open_observed') else 'MG995下颚自动动作已禁用：开合未稳定复现，请先检查连接与机械干涉。'
            tk.Label(w,text=text).pack()
            if jaw.get('drive_mode')=='fixed_points':tk.Label(w,text='下颚自动只切换已确认的两个端点；连续语音节奏首次运行请现场观察。').pack()
        row=tk.Frame(w);row.pack(fill='x',padx=8)
        self.tree=ttk.Treeview(row,columns=('name','pin','neutral','range','action','enabled'),show='headings',height=7)
        for key,label,width in (('name','部位',200),('pin','CH／J10',100),('neutral','中位',90),('range','范围',130),('action','动作点',100),('enabled','自动许可',180)):
            self.tree.heading(key,text=label);self.tree.column(key,width=width)
        scroll=ttk.Scrollbar(row,orient='vertical',command=self.tree.yview);self.tree.configure(yscrollcommand=scroll.set);self.tree.pack(side='left',fill='x',expand=True);scroll.pack(side='right',fill='y');self.tree.bind('<<TreeviewSelect>>',self.select_pose)
        row=tk.Frame(w);row.pack(pady=5)
        self.neutral=tk.IntVar(master=w,value=1500);self.lo=tk.IntVar(master=w,value=1100);self.hi=tk.IntVar(master=w,value=1900);self.action=tk.IntVar(master=w,value=1900);self.rate=tk.IntVar(master=w,value=150)
        for title,var in (('中位',self.neutral),('下限',self.lo),('上限',self.hi),('动作点',self.action),('速度μs/s',self.rate)):
            tk.Label(row,text=title).pack(side='left');tk.Spinbox(row,from_=20 if var is self.rate else 600,to=5000 if var is self.rate else 2400,textvariable=var,width=6).pack(side='left',padx=3)
        tk.Button(row,text='保存点位',command=self.save_pose).pack(side='left',padx=5);tk.Button(row,text='动作反向',command=self.reverse_pose).pack(side='left',padx=5)
        self.pose_ready=tk.BooleanVar(master=w,value=False)
        tk.Checkbutton(w,text='选中通道已接好，目标位置可现场观察，允许单次预览',variable=self.pose_ready).pack(anchor='w',padx=12)
        row=tk.Frame(w);row.pack(pady=5)
        tk.Button(row,text='单路预览并回中（≤400μs/s）',command=self.preview,width=30).pack(side='left',padx=8)
        tk.Button(row,text='已观察方向/中位正确，按所列速度允许自动',command=self.approve,width=34).pack(side='left',padx=8)
        row=tk.Frame(w);row.pack(pady=3)
        if self.life_config.get('jaw_setup'):
            self.jaw_manual=tk.IntVar(master=w,value=jaw['observed_open_us'] if jaw.get('operator_open_observed') else jaw['closed_us'])
            tk.Label(row,text='下颚手动 μs').pack(side='left')
            tk.Scale(row,from_=600,to=2400,resolution=1,orient='horizontal',variable=self.jaw_manual,length=250).pack(side='left')
            tk.Spinbox(row,from_=600,to=2400,textvariable=self.jaw_manual,width=6).pack(side='left',padx=4)
            tk.Button(row,text='下颚按手动值预览并回闭嘴',command=self.jaw_manual_preview).pack(side='left',padx=5)
            tk.Button(row,text='该张嘴点顺畅，记录',command=lambda:self.life_call(lambda:self.persist(self.control.record_jaw_open()))).pack(side='left',padx=5)
            tk.Button(row,text='使用已确认张嘴点说话',command=lambda:self.life_call(lambda:self.persist(self.control.use_jaw_for_speech(self.pose_ready.get())))).pack(side='left',padx=5)
        else:
            tk.Button(row,text='下颚−25μs探查并回中',command=lambda:self.jaw_probe(-1)).pack(side='left',padx=5)
            tk.Button(row,text='下颚＋25μs探查并回中',command=lambda:self.jaw_probe(1)).pack(side='left',padx=5)
        self.face_ready=tk.BooleanVar(master=w,value=False)
        tk.Checkbutton(w,text='所有已允许的自动动作点均已确认，允许联合表情',variable=self.face_ready).pack(anchor='w',padx=12)
        row=tk.Frame(w);row.pack(pady=6)
        for title,fn in (('开启表情（保留当前追踪）',self.enable),('停表情并柔和回位',self.disable),('立刻停面部PWM',self.immediate_stop),('单次眨眼',lambda:self.intent({'type':'blink'}))):tk.Button(row,text=title,command=fn).pack(side='left',padx=5)
        row=tk.Frame(w);row.pack(pady=4)
        for title,name in (('微笑','smile'),('难过','sad'),('右眼 wink','wink'),('回自然','neutral')):
            tk.Button(row,text=title,command=lambda n=name:self.play_preset(n)).pack(side='left',padx=4)
        self.preset_intensity=tk.DoubleVar(master=w,value=.8)
        tk.Label(row,text='强度').pack(side='left')
        tk.Scale(row,from_=.25,to=1.,resolution=.05,orient='horizontal',variable=self.preset_intensity,length=130).pack(side='left')
        tk.Button(row,text='右眼 wink 方向确认…',command=self.open_wink_setup).pack(side='left',padx=5)
        tk.Button(row,text='动作库…',command=self.open_action_library).pack(side='left',padx=5)
        row=tk.Frame(w);row.pack(pady=3)
        self.blink_pair_ready=tk.BooleanVar(master=w,value=False);self.blink_view_ready=tk.BooleanVar(master=w,value=False)
        tk.Checkbutton(row,text='已观察两眼同闭同睁',variable=self.blink_pair_ready).pack(side='left')
        tk.Checkbutton(row,text='已观察浅眨时摄像头仍能追踪',variable=self.blink_view_ready).pack(side='left')
        tk.Button(row,text='保存眨眼确认',command=self.confirm_blink).pack(side='left',padx=4)
        tk.Button(row,text='试眨一次（追踪时浅眨）',command=lambda:self.life_call(lambda:self.control.trial_tracking_blink(self.face_ready.get()))).pack(side='left',padx=4)
        row=tk.Frame(w);row.pack(pady=5)
        for title,style in (('柔和','soft'),('灵动','lively'),('活跃 · 快速大幅','active')):
            tk.Button(row,text=title,command=lambda value=style:self.set_expression_style_ui(value)).pack(side='left',padx=5)
        tk.Button(row,text='8秒无声表情演示',command=lambda:self.life_call(self.control.demo_expressions)).pack(side='left',padx=10)
        tk.Button(row,text='颈部标准',command=lambda:self.neck_speed('normal')).pack(side='left',padx=5)
        tk.Button(row,text='颈部加快',command=lambda:self.neck_speed('faster')).pack(side='left',padx=5)
        row=tk.Frame(w);row.pack(pady=6)
        self.audio_path=tk.StringVar(master=w,value='');tk.Entry(row,textvariable=self.audio_path,width=65).pack(side='left');tk.Button(row,text='选择语音文件',command=self.choose_audio).pack(side='left',padx=5)
        tk.Button(row,text='播放并联动',command=self.play_audio).pack(side='left',padx=5);tk.Button(row,text='停止语音',command=self.audio.stop).pack(side='left',padx=5)
        row=tk.Frame(w);row.pack(pady=6)
        tk.Button(row,text='启动本机LLM/TTS接口',command=self.start_api).pack(side='left',padx=5)
        self.api_text=tk.StringVar(master=w,value='本机接口尚未启动');tk.Label(row,textvariable=self.api_text).pack(side='left')
        self.life_status=tk.StringVar(master=w,value='当前仅准备点位；没有新增面部输出。')
        tk.Label(w,textvariable=self.life_status,wraplength=1020,font=('Microsoft YaHei UI',11)).pack(pady=9)
        tk.Label(w,text='wink仅用右上眼帘，需确认摄像头画面无遮挡。双眼眨眼关闭，左上及左下眼帘自动屏蔽（含开启及回位）；颈部仍限±100μs。',wraplength=1010).pack(pady=5)
        w.protocol('WM_DELETE_WINDOW',self.keep_window);self.refresh();selected='21' if jaw else '2';self.tree.selection_set(selected);self.tree.see(selected);self.select_pose()
    def selected(self):
        selected=self.tree.selection()
        if not selected:raise ValueError('Select an action row')
        return int(selected[0])
    def pose(self,ch):return next(p for p in self.life_config['poses'] if p['channel']==ch)
    def refresh(self):
        pins={r['channel']:r['signal_pin'] for r in json.loads((ROOT/'config/face_commission.json').read_text(encoding='utf-8'))['channels']}
        for p in self.life_config['poses']:
            values=(p['label'],f"{p['channel']} / {pins[p['channel']]}",p['neutral_us'],f"{p['min_us']}–{p['max_us']}",str(p['action_us'])+' '+p['action_label'],'自动屏蔽（干扰视觉）' if p.get('automatic_inhibited') else '已确认' if p['enabled'] and p['action_verified'] else '方向待确认')
            if self.tree.exists(str(p['channel'])):self.tree.item(str(p['channel']),values=values)
            else:self.tree.insert('',tk.END,iid=str(p['channel']),values=values)
    def select_pose(self,*_):
        try:p=self.pose(self.selected())
        except ValueError:return
        for var,key in ((self.neutral,'neutral_us'),(self.lo,'min_us'),(self.hi,'max_us'),(self.action,'action_us'),(self.rate,'max_rate_us_per_s')):var.set(p[key])
        self.pose_ready.set(False)
    def life_call(self,fn):
        try:fn()
        except Exception as exc:self.life_status.set('未执行：'+str(exc))
    def persist(self,cfg):
        self.life_config=cfg;write_status(CONFIG,cfg);self.refresh()
    def save_pose(self):
        def work():
            p=copy.deepcopy(self.pose(self.selected()));p.update(neutral_us=self.neutral.get(),min_us=self.lo.get(),max_us=self.hi.get(),action_us=self.action.get(),max_rate_us_per_s=self.rate.get(),range_confirmed=self.pose_ready.get())
            self.persist(self.control.update_pose(p));self.life_status.set('点位已保存，自动许可已清除；预览后再确认方向。')
        self.life_call(work)
    def reverse_pose(self):
        self.action.set(max(self.lo.get(),min(self.hi.get(),2*self.neutral.get()-self.action.get())));self.save_pose()
    def preview(self):
        if self.selected()==21 and hasattr(self,'jaw_manual'):return self.jaw_manual_preview()
        self.life_call(lambda:self.control.preview_joint(self.selected(),self.pose_ready.get()))
    def jaw_manual_preview(self):self.life_call(lambda:self.control.preview_jaw_manual(self.jaw_manual.get(),self.pose_ready.get()))
    def jaw_probe(self,direction):
        def work():
            if self.selected()!=21:raise ValueError('请先选择下颚并勾选本路接线确认')
            self.control.probe_jaw(direction,self.pose_ready.get())
        self.life_call(work)
    def approve(self):
        def work():self.persist(self.control.approve_pose(self.selected()));self.life_status.set('本路方向和中位观察已保存；下次启用活人感才参与自动输出。')
        self.life_call(work)
    def enable(self):
        def work():
            self.control.enable_life(self.face_ready.get())
            count=len(self.control.extra.get('life_ready_channels',[]));self.life_status.set('表情已开启，已确认自动面部%d路；原有眼颈追踪保持当前状态。'%count)
        self.life_call(work)
    def disable(self):self.audio.stop();self.life_call(lambda:self.control.disable_life())
    def confirm_blink(self):
        def work():
            self.persist(self.control.set_blink_policy(self.blink_pair_ready.get(),self.blink_view_ready.get()))
            self.life_status.set('眨眼确认已保存；追踪中双眼只浅眨20%，右眼相机视野未确认时不自动眨眼。')
        self.life_call(work)
    def immediate_stop(self):self.audio.stop();self.life_call(lambda:self.control.disable_life(True))
    def intent(self,event):self.life_call(lambda:self.control.life_event(event))
    def play_preset(self,name):
        def work():
            self.control.life_event(dict(type='expression',name=name,duration_s=3,intensity=self.preset_intensity.get()))
            self.life_status.set({'smile':'微笑','sad':'难过','wink':'右眼 wink','neutral':'回自然'}[name]+'已触发；保持当前眼颈追踪和语音嘴形。')
        self.life_call(work)
    def open_wink_setup(self):
        if hasattr(self,'wink_window') and self.wink_window.winfo_exists():self.wink_window.lift();return
        w=tk.Toplevel(self.life_window);self.wink_window=w;w.title('右眼 wink · 方向与画面确认');w.geometry('660x320')
        tk.Label(w,text='仅右上眼帘CH8（Pin11）做wink；左上眼帘及两侧下眼帘不叠加wink动作。',wraplength=620).pack(pady=14)
        tk.Label(w,text='开启本窗口会话和表情后试一次。确认右眼闭合再回张，且摄像头画面无遮挡。若在睁大，先停下并重新标定右上眼帘方向。',wraplength=620).pack(pady=5)
        ready=tk.BooleanVar(master=w,value=False);observed=tk.BooleanVar(master=w,value=False)
        tk.Checkbutton(w,text='头部托稳、可观察右眼及摄像头画面，允许一次试动作',variable=ready).pack(pady=5)
        tk.Button(w,text='试一次右眼 wink',command=lambda:self.life_call(lambda:self.control.trial_right_wink(ready.get()))).pack(pady=6)
        tk.Checkbutton(w,text='已观察右眼闭合并回张，摄像头画面无遮挡且跟随正常',variable=observed).pack(pady=5)
        def approve():
            self.persist(self.control.approve_right_wink(observed.get()));self.life_status.set('右眼 wink 已确认，可以从快捷按钮或对话意图触发。');w.destroy()
        tk.Button(w,text='保存观察确认，开放快捷 wink',command=lambda:self.life_call(approve)).pack(pady=6)
        tk.Label(w,textvariable=self.life_status,wraplength=620).pack(pady=5)
    def open_action_library(self):
        from action_library import CATALOG
        if hasattr(self,'action_window') and self.action_window.winfo_exists():self.action_window.lift();return
        w=tk.Toplevel(self.life_window);self.action_window=w;w.title('自然语言动作库 · 许可与单次调试');w.geometry('860x680')
        tk.Label(w,text='大模型选动作ID → 动作库校验 → 唯一控制器执行 → 回到原追踪',font=('Microsoft YaHei UI',13,'bold')).pack(pady=12)
        ready=tk.BooleanVar(master=w,value=False)
        tk.Checkbutton(w,text='接线、供电、共地保持正常，动作空间无遮挡，可现场观察各动作方向',variable=ready).pack(pady=7)
        row=tk.Frame(w);row.pack(pady=8)
        tk.Button(row,text='开启动作库（仅本会话）',command=lambda:self.life_call(lambda:self.control.set_action_library(True,ready.get()))).pack(side='left',padx=5)
        tk.Button(row,text='关闭动作库',command=lambda:self.life_call(lambda:self.control.set_action_library(False))).pack(side='left',padx=5)
        tk.Button(row,text='取消动作并回原位',command=lambda:self.intent({'type':'action.cancel'})).pack(side='left',padx=5)
        row=tk.Frame(w);row.pack(pady=5)
        settings=self.control.extra.get('eye_gesture') or dict(delta_us=300,rate_us_per_s=300)
        self.eye_gesture_delta=tk.IntVar(master=w,value=settings['delta_us']);self.eye_gesture_rate=tk.IntVar(master=w,value=settings['rate_us_per_s'])
        tk.Label(row,text='抬眼幅度μs').pack(side='left')
        tk.Spinbox(row,from_=100,to=400,increment=25,textvariable=self.eye_gesture_delta,width=5).pack(side='left',padx=5)
        tk.Label(row,text='抬眼速度μs/s').pack(side='left')
        tk.Spinbox(row,from_=100,to=300,increment=25,textvariable=self.eye_gesture_rate,width=5).pack(side='left',padx=5)
        def update_eye():
            self.control.set_eye_gesture(self.eye_gesture_delta.get(),self.eye_gesture_rate.get(),ready.get())
            self.life_status.set('抬眼参数已更新，仅本会话生效；尚未执行动作。')
        tk.Button(row,text='更新抬眼参数（不执行）',command=lambda:self.life_call(update_eye)).pack(side='left',padx=6)
        row=tk.Frame(w);row.pack(pady=4)
        head_settings=self.control.extra.get('head_gesture') or dict(yaw_rate_us_per_s=120,pitch_rate_us_per_s=100)
        self.head_gesture_yaw=tk.IntVar(master=w,value=head_settings['yaw_rate_us_per_s']);self.head_gesture_pitch=tk.IntVar(master=w,value=head_settings['pitch_rate_us_per_s'])
        tk.Label(row,text='摇头速度μs/s').pack(side='left')
        tk.Spinbox(row,from_=20,to=150,increment=10,textvariable=self.head_gesture_yaw,width=5).pack(side='left',padx=5)
        tk.Label(row,text='抬头速度μs/s').pack(side='left')
        tk.Spinbox(row,from_=15,to=100,increment=5,textvariable=self.head_gesture_pitch,width=5).pack(side='left',padx=5)
        def update_head():
            self.control.set_head_gesture_rates(self.head_gesture_yaw.get(),self.head_gesture_pitch.get(),ready.get())
            self.life_status.set('头部动作速度已更新，仅本会话生效；尚未执行动作。')
        tk.Button(row,text='更新头部速度（不执行）',command=lambda:self.life_call(update_head)).pack(side='left',padx=6)
        tk.Label(w,text='下面是直接调试；语义界面输入“请你抬起头”等句子才经过大模型分析。\n头眼动作暂时接管相关轴，完成后恢复追踪。正面接力＋动作库开启时预留80μs抬头余量；必要时先等待追踪分配。手动抬头到边界会提示；抬眼余量不足时会先回参考。当前默认抬眼/抬头/摇头约3.4/3.7/5.7秒，起点不同会变化；微笑/难过需开启表情，wink需方向确认。',wraplength=740).pack(pady=8)
        for name,item in CATALOG.items():
            row=tk.Frame(w);row.pack(fill='x',padx=18,pady=4)
            tk.Button(row,text='单次：'+item['label'],width=17,command=lambda n=name:self.intent(dict(type='action',request_id=uuid.uuid4().hex,actions=[n]))).pack(side='left')
            tk.Label(row,text=item['description']).pack(side='left',padx=12)
        self.action_status=tk.StringVar(master=w,value='动作库默认关闭；这里不会自动开启PWM。')
        tk.Label(w,textvariable=self.action_status,wraplength=735).pack(pady=12)
        tk.Label(w,textvariable=self.life_status,wraplength=735).pack(pady=4)
    def set_expression_style_ui(self,value):
        def work():
            self.persist(self.control.set_expression_style(value));self.life_status.set('已切换表情强度：'+{'soft':'柔和','lively':'灵动','active':'活跃 · 快速大幅'}[value])
        self.life_call(work)
    def neck_speed(self,value):
        def work():
            self.persist(self.control.set_neck_tracking_speed(value));self.life_status.set('颈部追踪速度：'+('40/30μs/s；行程仍为±100μs' if value=='faster' else '20/15μs/s；行程仍为±100μs'))
        self.life_call(work)
    def choose_audio(self):
        path=filedialog.askopenfilename(parent=self.life_window,title='选择语音文件',filetypes=[('Audio','*.wav *.mp3 *.m4a *.flac *.ogg'),('All','*.*')])
        if path:self.audio_path.set(path)
    def play_audio(self):self.life_call(lambda:self.audio.play(self.audio_path.get()))
    def start_api(self):
        def work():
            if self.api is None:
                self.api=IntentServer(self.control).start();write_status(ROOT/'build/lifelike_api.json',dict(url='http://127.0.0.1:'+str(self.api.port),key=self.api.token,pid=os.getpid()))
            self.api_text.set('127.0.0.1:%d；接入密钥见build/lifelike_api.json'%self.api.port)
        self.life_call(work)
    def poll(self):
        super().poll()
        if not hasattr(self,'life_status'):return
        self.session_text.set('本窗口PID%d：%s；活人感%s；自动许可%d路'%(os.getpid(),self.control.mode,self.control.extra.get('life_state'),len(self.control.extra.get('life_ready_channels',[]))))
        while True:
            try:kind,text=self.events.get_nowait()
            except queue.Empty:break
            self.life_status.set(text)
        extra=self.control.extra;t=extra.get('life_preview')
        if hasattr(self,'action_window') and self.action_window.winfo_exists():
            from action_library import describe_action
            self.action_status.set('动作库'+('开' if extra.get('action_library_enabled') else '关')+'；抬头可用'+str(extra.get('head_up_room_us','--'))+'μs；'+describe_action(extra.get('action_active'),extra.get('action_last')))
        if t:self.life_status.set('CH%d单路预览中，目标%dμs，完成后回中关闭。'%(t['channel'],t['target_us']))
        elif extra.get('life_last_preview') and self.life_status.get().startswith('CH'):self.life_status.set('预览已回中并关闭。若方向和中位正确，点允许自动；若相反，保存反向后再预览。')
    def pause(self):
        if hasattr(self,'audio'):self.audio.stop()
        return super().pause()
    def end(self):
        if hasattr(self,'audio'):self.audio.stop()
        return super().end()
    def keep_window(self):self.immediate_stop();self.life_status.set('窗口保留，面部PWM已请求关闭。')
    def close(self):
        if self.control.mode!='idle':self.pause();return
        self.audio.stop()
        if self.api:self.api.stop()
        super().close()
def main():
    p=argparse.ArgumentParser();p.add_argument('--self-test',action='store_true');a=p.parse_args();w=tk.Tk()
    if a.self_test:w.withdraw()
    panel=LifelikePanel(w)
    if a.self_test:
        panel.life_window.withdraw();w.update_idletasks();assert panel.control.mode=='idle' and panel.control.client is None and panel.api is None
        panel.control.close();w.destroy();print('LIFELIKE_PANEL_IDLE_SMOKE_PASS')
    else:w.mainloop()
if __name__=='__main__':main()
