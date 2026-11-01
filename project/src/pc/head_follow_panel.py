from shared_hardware import SHARED_VISION_LOG,SHARED_VISION_STOP
"""Unified eye/neck commissioning panel. Opening remains idle and preserves other windows."""
import argparse,json,os,subprocess,sys,time,tkinter as tk
from pathlib import Path
from head_session import HeadSession
from neck_yaw_midpoint import ROOT
from neck_presets import neck_neutral,rod_preset
from head_coordination import camera_setup_signature
from runtime_logs import write_status
from vision_bridge import latest

def load_profile():
    neck=json.loads((ROOT/'config/neck_follow.json').read_text(encoding='utf-8-sig'))
    head=json.loads((ROOT/'config/head_follow.json').read_text(encoding='utf-8-sig'))
    camera=json.loads((ROOT/'config/camera.json').read_text(encoding='utf-8-sig'))
    head['camera_setup_signature']=camera_setup_signature(dict(neck,**head),camera)
    head['camera_frame_size']=[camera['width'],camera['height']]
    saved=ROOT/'build/head_neck_direction_last_good.json'
    if saved.exists():
        try:head['saved_direction_record']=json.loads(saved.read_text(encoding='utf-8-sig'))
        except (OSError,ValueError):pass
    return dict(neck,**head)

class Panel:
    def __init__(self,window,controller_factory=HeadSession):
        self.ignore_scale_values={};self.window=window;self.control=controller_factory(load_profile());self.syncing=False;self.camera=None
        self.last_status=0.;self.saved_result=None;self.saved_good=None;self.future_ready=False
        self.path=ROOT/'build'/('head_runtime_'+str(os.getpid())+'.json')
        window.title('NeuroHead 眼球＋脖子联调 v6 · 重启恢复与连贯动作 · 五路统一控制');window.geometry('1000x880')
        tk.Label(window,text='眼球＋脖子 · 五路联调',font=('Microsoft YaHei UI',21,'bold')).pack(pady=12)
        tk.Label(window,text='眼睛：左右Pin10／上下Pin4；脖子：左右Pin21／左杆Pin22／右杆Pin23。全部外部5V供电并共地。').pack()
        tk.Label(window,text='相机随眼球转动。开始时眼睛1500／1500，脖子1500／1270／1500μs。').pack(pady=4)
        self.style=tk.StringVar(master=window,value=self.control.profile.get('motion_style','natural'))
        style_row=tk.Frame(window);style_row.pack(pady=5)
        tk.Label(style_row,text='动作曲线：').pack(side='left')
        for title,value in (('柔和连贯','natural'),('原动作对照','legacy')):
            tk.Radiobutton(style_row,text=title,variable=self.style,value=value,command=self.apply_style).pack(side='left',padx=14)
        self.ready=tk.BooleanVar(master=window,value=False)
        tk.Checkbutton(window,text='已确认五根信号线及外部供电接好、眼睛已装回，头部托稳并可现场观察',variable=self.ready).pack(pady=4)
        self.status=tk.StringVar(master=window,value='本窗口未连接板卡。若其他窗口正在控制，请先托稳并在该窗口结束，再勾选现场确认并开始。')
        self.readback=tk.StringVar(master=window,value='尚未连接');self.vision_text=tk.StringVar(master=window,value='USB Cam画面检查中')
        self.sliders=[]
        limits=[(1100,1900),tuple(self.control.profile.get('eye_vertical_limits_us',[1000,2000]))]+[(1100,1900)]*3
        for i,(name,neutral,(lo,hi)) in enumerate(zip(('眼睛左右 · Pin10','眼睛上下 · Pin4','脖子左右 · Pin21','左杆 · Pin22','右杆 · Pin23'),self.control.reference,limits)):
            row=tk.Frame(window);row.pack(pady=2)
            tk.Label(row,text=name,width=25,anchor='w').pack(side='left')
            scale=tk.Scale(row,from_=lo,to=hi,resolution=1,orient='horizontal',length=470);scale.set(neutral);scale.pack(side='left')
            scale.configure(command=lambda value,index=i:self.changed(index));self.sliders.append(scale)
        row=tk.Frame(window);row.pack(pady=8)
        for text,callback in (('打开／复用USB Cam预览',self.open_camera),('开始五路控制',self.start),('暂停并保持',self.pause),('已托稳，结束停PWM',self.end)):
            tk.Button(row,text=text,command=callback,width=24).pack(side='left',padx=3)
        row=tk.Frame(window);row.pack(pady=8)
        for text,callback in (('眼球跟随，脖子手动',lambda:self.follow('eyes')),('重新辨识（可选）',self.identify),('眼球＋脖子接力试运行',lambda:self.follow('coordinated'))):
            tk.Button(row,text=text,command=callback,width=29).pack(side='left',padx=4)
        row=tk.Frame(window);row.pack(pady=6)
        for text,callback in (('全部回中',self.home),('脖子左升右降',lambda:self.neck_preset(1,-1)),('脖子左降右升',lambda:self.neck_preset(-1,1)),('仅手动控制',lambda:self.follow('manual'))):
            tk.Button(row,text=text,command=callback,width=20).pack(side='left',padx=4)
        tk.Label(window,text='柔和模式：缓起缓停、连续换向、短暂丢脸保持；沿用参考±100μs和20／15μs/s。').pack(pady=4)
        tk.Label(window,textvariable=self.vision_text,font=('Microsoft YaHei UI',11)).pack(pady=5)
        tk.Label(window,textvariable=self.readback,font=('Microsoft YaHei UI',12),wraplength=940).pack(pady=8)
        tk.Label(window,textvariable=self.status,font=('Microsoft YaHei UI',11),wraplength=930).pack(pady=8)
        tk.Label(window,text='滑块为实际PWM；Pin22中位1270。移动眼睛滑块切回手动；只调脖子时可保留眼球跟随。').pack(pady=4)
        tk.Label(window,text='画面过期或相机重启时保持当前位置；通信中断时颈部按硬件策略保持。旧窗口与相机窗口保留。').pack(pady=4)
        window.protocol('WM_DELETE_WINDOW',self.close);window.after(100,self.poll)
    def sync(self,values):
        self.syncing=True
        for i,(slider,value) in enumerate(zip(self.sliders,values)):
            if int(slider.get())!=value:self.ignore_scale_values[i]=value
            slider.set(value)
        self.syncing=False
    def call(self,fn):
        try:fn()
        except Exception as exc:self.status.set('未执行：'+str(exc))
    def changed(self,index):
        if self.syncing:return
        if self.control.mode in ('running','paused') and self.control.extra.get('tracking')=='coordinated':
            self.sync(self.control.desired)
            self.status.set('正面接力中滑块只读；需要手动调试请先点“仅手动控制”。')
            return
        shown=int(self.sliders[index].get())
        if self.ignore_scale_values.pop(index,None)==shown:return
        if shown==self.control.desired[index]:return
        def action():
            if self.control.mode in ('running','paused'):
                kind=self.control.extra['tracking']
                if kind=='identify' or index<2:self.control.set_follow('manual')
                elif kind=='coordinated':self.control.set_follow('eyes')
            values=list(self.control.desired);values[index]=int(self.sliders[index].get());self.control.set_targets(values)
        self.call(action)
    def apply_style(self):
        def action():
            style=self.style.get();self.control.set_motion_style(style)
            path=ROOT/'config/head_follow.json';p=json.loads(path.read_text(encoding='utf-8-sig'));p['motion_style']=style;write_status(path,p)
            self.status.set('已应用柔和曲线，保持当前姿态并逐渐接续。' if style=='natural' else '已应用原动作曲线作对照。')
        self.call(action)
    def start(self):
        if not self.ready.get():self.status.set('请先确认当前五路接线、外部供电及头部支撑，再勾选现场确认。');return
        def action():
            p=dict(self.control.profile);p['operator_ready_this_session']=True;self.control.profile=p
            self.control.start();self.status.set('五路统一控制已开始。已有方向存档时可直接点眼球＋脖子接力试运行。')
        self.call(action)
    def pause(self):
        def action():self.control.pause();self.sync(self.control.output);self.status.set('已暂停并保持五路当前位置。')
        if self.control.mode!='idle':self.call(action)
    def end(self):
        def action():
            self.control.end(head_supported=True);self.status.set('已确认PWM关闭；窗口保留。');self.sync(self.control.reference)
            write_status(ROOT/'build/head_active.json',self.snapshot())
        if self.control.mode!='idle':self.call(action)
    def follow(self,kind):
        def action():
            self.control.set_follow(kind)
            self.status.set({'manual':'已切回手动，保持当前位置。','eyes':'眼球持续跟随，脖子可手动配合。','coordinated':'眼球与脖子持续接力，脖子不自动侧倾。'}[kind])
        self.call(action)
    def home(self):
        def action():
            if self.control.mode in ('running','paused'):self.control.set_follow('manual')
            self.control.set_targets(self.control.reference);self.sync(self.control.reference)
            self.status.set('已设置五路中位；暂停状态需要点击开始继续。')
        self.call(action)
    def neck_preset(self,left,right):
        def action():
            if self.control.extra.get('tracking')=='coordinated':raise ValueError('正面接力中请先点“仅手动控制”，再测试颈部姿态')
            if self.control.mode in ('running','paused'):
                current=self.control.extra['tracking']
                self.control.set_follow('eyes' if current in ('eyes','coordinated') else 'manual')
            values=self.control.desired[:2]+rod_preset(neck_neutral(self.control.profile)[0],left,right,self.control.profile)
            self.control.set_targets(values);self.sync(values)
        self.call(action)
    def identify(self):
        def action():
            self.control.identify();self.status.set('辨识中：人脸与机器人保持不动，程序会小幅左右转头和俯仰并回中，约30秒。')
        self.call(action)
    def open_camera(self):
        try:
            row=latest(SHARED_VISION_LOG)
            if 0<=time.monotonic()-row['host_monotonic_s']<.75:
                self.status.set('复用现有USB Cam预览；未关闭或重复打开相机。');return
        except (OSError,ValueError,KeyError):pass
        if self.camera is not None and self.camera.poll() is None:self.status.set('正在等待USB Cam启动。');return
        (SHARED_VISION_STOP).unlink(missing_ok=True)
        path=ROOT/'build/head_camera.log'
        with path.open('ab') as handle:
            self.camera=subprocess.Popen([sys.executable,str(ROOT/'src/pc/external_vision_source.py'),'--show','--duration','0'],cwd=ROOT,
                stdout=handle,stderr=subprocess.STDOUT,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        self.status.set('正在打开外接USB Cam。')
    def snapshot(self):
        state=self.control.last_state or {}
        return dict(ui_message=self.status.get(),mode=self.control.mode,owner_pid=os.getpid(),updated_epoch=time.time(),desired_us=self.control.desired,
            output_pwm_us=self.control.output,reference_us=self.control.reference,board_status=state.get('status'),
            active_mask=state.get('active_mask'),error=self.control.error,worker_max_gap_s=self.control.max_active_gap_s,**self.control.extra)
    def poll(self):
        snap=self.snapshot();extra=self.control.extra
        for slider in self.sliders:slider.configure(state='disabled' if extra.get('tracking')=='coordinated' else 'normal')
        try:
            row=latest(SHARED_VISION_LOG);fresh=0<=time.monotonic()-row['host_monotonic_s']<.75
            self.vision_text.set('USB Cam：'+('人脸已检测' if row['vision'].get('target') is not None else '未检测到人脸') if fresh else 'USB Cam：画面未更新')
        except (OSError,ValueError,KeyError):self.vision_text.set('USB Cam：等待画面')
        kind={'manual':'五路手动','eyes':'眼球跟随／脖子手动','identify':'方向辨识中','coordinated':'眼颈接力运行'}.get(extra.get('tracking'),'未知')
        self.readback.set('状态：%s · %s · %s | PWM回读[眼左右,眼上下,颈左右,左杆,右杆]：%s'%(self.control.mode,kind,'柔和' if extra.get('motion_style')=='natural' else '原动作',self.control.output))
        if extra.get('identification_phase'):self.status.set('正在辨识：'+extra['identification_phase']+'；请保持脸和机器人不动。')
        result=extra.get('identification_result')
        if result is not None and result!=self.saved_result:
            write_status(ROOT/'build/head_neck_camera_calibration.json',result);self.saved_result=result
            archive=ROOT/'build'/('head_identification_'+str(int(result.get('completed_epoch',time.time())*1000))+'.json')
            if not archive.exists():write_status(archive,result)
            self.status.set(('局部方向辨识通过；回中画面有漂移，接力仅低速±100μs试运行。' if result.get('calibration',{}).get('provisional_direction_only') else '方向辨识通过，可点击眼球＋脖子接力试运行。') if result.get('success') else ('本次辨识未通过，上一组方向已保留：' if extra.get('last_good_direction') else '辨识未通过，已保持：')+result.get('error',''))
        good=extra.get('last_good_direction')
        if good is not None and good!=self.saved_good:
            write_status(ROOT/'build/head_neck_direction_last_good.json',good);self.saved_good=good
        if self.control.mode=='fault':self.status.set('控制异常，已停止更新；托稳后结束并核对：'+self.control.error)
        elif extra.get('note','').startswith('Visual control held'):self.status.set('视觉已暂停并保持：'+extra['note'])
        if time.monotonic()-self.last_status>.25:
            write_status(self.path,snap)
            if self.control.mode!='idle':write_status(ROOT/'build/head_active.json',snap)
            self.last_status=time.monotonic()
        self.window.after(100,self.poll)
    def close(self):
        if self.control.mode=='idle':self.control.close();self.window.destroy()
        else:self.pause();self.status.set('窗口保留。关闭前请托稳头部并点击结束停PWM。')

def main():
    p=argparse.ArgumentParser();p.add_argument('--self-test',action='store_true');a=p.parse_args()
    w=tk.Tk()
    if a.self_test:w.withdraw()
    panel=Panel(w)
    if a.self_test:
        w.update_idletasks();assert panel.control.mode=='idle' and panel.control.client is None
        assert len(panel.sliders)==5 and not panel.ready.get();panel.control.close();w.destroy();print('HEAD_PANEL_IDLE_SMOKE_PASS')
    else:w.mainloop()
if __name__=='__main__':main()
