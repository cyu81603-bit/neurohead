"""Will Cogley geometry + PyBullet visualization, with read-only AX7020 UDP.

No actuator command encoder or motion sender is imported. Demonstration degrees
and PWM display conversion are NOT measured hardware angles or safe limits.
"""
import argparse
from datetime import datetime
import json
import math
import os
from pathlib import Path
import socket
import sys
import time
import threading
from collections import deque

ROOT = Path(__file__).resolve().parents[2]
_dll = None
if os.name=='nt' and (Path(sys.prefix)/'Library/bin').is_dir():
    _dll = os.add_dll_directory(str(Path(sys.prefix)/'Library/bin'))
import numpy as np
from PIL import Image, ImageDraw, ImageFont
import pybullet as p
from monitor_protocol import make_query, parse_telemetry
from visual_gaze import VisualGaze
from vision_source import VisionSource
from session_report import export_session
from board_network import bind_board_socket

MODEL = ROOT/'build/visualization_assets/will_cogley_head/head.urdf'
FAST_MODEL = ROOT/'build/visualization_assets/will_cogley_head_fast/head.urdf'
REPLAY = ROOT/'data/detached_diagnostics/20261019_221331_755060_board.json'
POSE_KEYS = ('neck_pan','neck_tilt','neck_roll','eye_pan','eye_tilt','jaw_open')


def make_gaze(controller):
    if controller=='visp':
        from visp_gaze_proxy import VispGazeProxy
        return VispGazeProxy()
    return VisualGaze()


def close_gaze(gaze):
    if hasattr(gaze,'close'):gaze.close()


def gaze_diagnostics(gaze):
    return gaze.diagnostics() if hasattr(gaze,'diagnostics') else dict(backend='illustrative_mapping')


def synthetic_target(t):
    return [.75*math.sin(t*.4),.45*math.sin(t*.28)]


def display_pose(state):
    """Explicit illustrative scale only: 1000 us = 60 display degrees."""
    result = dict.fromkeys(POSE_KEYS,0.0)
    for field,key in (('output_yaw_us','eye_pan'),('output_pitch_us','eye_tilt')):
        value = state[field]
        if not isinstance(value,(int,float)) or not math.isfinite(value) or not 600<=value<=2400:
            raise ValueError('Invalid PWM setting')
        result[key] = max(-45,min(45,(value-1500)*.06))
    return result


class ReadOnlyBoard:
    def __init__(self):
        self.peer=('192.168.10.20',5005)
        self.sock=socket.socket(socket.AF_INET,socket.SOCK_DGRAM)
        try:
            self.interface_index=bind_board_socket(self.sock)
        except OSError:
            self.sock.close()
            raise
        self.sock.setblocking(False)
        self.pending={}
        self.state=None
        self.last_rx=self.last_tx=0.0
        self.token=int(time.monotonic()*1000)&0xffffffff
        self.queries=self.replies=0
        self.error=''
        self.last_rtt_ms=None

    def tick(self):
        now=time.monotonic()
        for _ in range(64):
            try: raw,addr=self.sock.recvfrom(2048)
            except BlockingIOError: break
            if addr!=self.peer: continue
            try: state=parse_telemetry(raw)
            except ValueError: continue
            token=state['echo_timestamp_ms']
            if not state['query'] or state['simulated'] or token not in self.pending: continue
            sent=self.pending.pop(token)
            self.last_rtt_ms=(time.perf_counter()-sent)*1000
            self.state,self.last_rx=state,now
            self.replies+=1
        self.pending={k:v for k,v in self.pending.items() if time.perf_counter()-v<.3}
        if now-self.last_tx>=.1:
            self.token=(self.token+1)&0xffffffff
            # The sole network transmission in this application: NQ read query.
            packet=make_query(self.queries&0xffff,self.token)
            assert packet[:2]==b'NQ' and len(packet)==12
            self.pending[self.token]=time.perf_counter()
            self.sock.sendto(packet,self.peer)
            self.queries+=1
            self.last_tx=now

    @property
    def fresh(self):
        return self.state is not None and time.monotonic()-self.last_rx<.6

    def close(self): self.sock.close()


class ReadOnlyBoardMonitor:
    """Poll independently of 3D rendering; only constructs the NQ-only client."""
    def __init__(self,factory=ReadOnlyBoard):
        self.factory=factory
        self.lock=threading.Lock();self.stop_event=threading.Event()
        self.values=dict(state=None,queries=0,replies=0,last_rx=0.,last_rtt_ms=None,error='等待连接',interface_index=None)
        self.thread=threading.Thread(target=self._run,name='ax7020_readonly',daemon=True)
        self.thread.start()

    def _run(self):
        client=None
        try:
            while not self.stop_event.is_set():
                try:
                    if client is None:client=self.factory()
                    client.tick()
                    with self.lock:self.values=dict(state=client.state,queries=client.queries,
                        replies=client.replies,last_rx=client.last_rx,last_rtt_ms=client.last_rtt_ms,
                        interface_index=client.interface_index,error='')
                    self.stop_event.wait(.01)
                except OSError as exc:
                    if client:client.close();client=None
                    with self.lock:self.values=dict(self.values,error=str(exc),last_rx=0.)
                    self.stop_event.wait(2)
        finally:
            if client:client.close()

    def snapshot(self):
        with self.lock:data=dict(self.values)
        data['fresh']=data['state'] is not None and time.monotonic()-data['last_rx']<.6
        return data

    @property
    def state(self):return self.snapshot()['state']
    @property
    def fresh(self):return self.snapshot()['fresh']
    @property
    def queries(self):return self.snapshot()['queries']
    @property
    def replies(self):return self.snapshot()['replies']
    def close(self):
        self.stop_event.set();self.thread.join(timeout=1)


class Replay:
    def __init__(self,path=REPLAY):
        data=json.loads(Path(path).read_text(encoding='utf-8'))
        self.rows=[]
        offset=0
        for step in data['results']:
            for row in step['samples']:
                self.rows.append((offset+row['elapsed_s'],row))
            offset=self.rows[-1][0]+.2
        if not self.rows: raise ValueError('Empty recording')
        self.duration=self.rows[-1][0]+1
        self.physical_observation=data.get('physical_observation','not_recorded')

    def at(self,seconds):
        t=seconds%self.duration
        return next((row for stamp,row in reversed(self.rows) if stamp<=t),self.rows[0][1])


class HeadScene:
    def __init__(self,gui=False,model=MODEL):
        self.gui=gui
        self.client=p.connect(p.GUI if gui else p.DIRECT,options='--width=1100 --height=850' if gui else '')
        self.robot=p.loadURDF(str(model),useFixedBase=True,
                              physicsClientId=self.client)
        self.joints={p.getJointInfo(self.robot,i,physicsClientId=self.client)[1].decode():i
                     for i in range(p.getNumJoints(self.robot,physicsClientId=self.client))}
        for link in range(-1,len(self.joints)):
            p.setCollisionFilterGroupMask(self.robot,link,0,0,physicsClientId=self.client)
        self.yaw,self.pitch,self.distance=18,-7,.70
        if gui:
            p.configureDebugVisualizer(p.COV_ENABLE_GUI,0,physicsClientId=self.client)
            p.resetDebugVisualizerCamera(self.distance,self.yaw,self.pitch,[0,-.008,.26],physicsClientId=self.client)
        floor=p.createVisualShape(p.GEOM_BOX,halfExtents=[.22,.19,.006],rgbaColor=[.13,.23,.31,1],physicsClientId=self.client)
        p.createMultiBody(baseMass=0,baseVisualShapeIndex=floor,basePosition=[0,0,-.006],physicsClientId=self.client)

    def pose(self,angles):
        values={key:angles.get(key,0) for key in ('neck_pan','neck_tilt','neck_roll','jaw_open')}
        for eye in ('eye_left','eye_right'):
            values[eye+'_pan']=angles.get('eye_pan',0)
            values[eye+'_tilt']=angles.get('eye_tilt',0)
        for key,value in values.items():
            p.resetJointState(self.robot,self.joints[key],math.radians(value),physicsClientId=self.client)

    def render(self,width=900,height=650,shadows=True):
        view=p.computeViewMatrixFromYawPitchRoll([0,-.008,.26],self.distance,self.yaw,self.pitch,0,2)
        proj=p.computeProjectionMatrixFOV(42,width/height,.01,3)
        rgba=p.getCameraImage(width,height,view,proj,renderer=p.ER_BULLET_HARDWARE_OPENGL if self.gui else p.ER_TINY_RENDERER,
                              lightDirection=[-1,-2,3],shadow=int(shadows),
                              flags=p.ER_NO_SEGMENTATION_MASK,physicsClientId=self.client)[2]
        return Image.fromarray(np.asarray(rgba,dtype=np.uint8).reshape(height,width,4)[:,:,:3])

    def close(self): p.disconnect(self.client)


def demo_pose(t):
    return dict(neck_pan=15*math.sin(t*.45),neck_tilt=6*math.sin(t*.6),
                neck_roll=4*math.sin(t*.37),eye_pan=18*math.sin(t*1.1),
                eye_tilt=7*math.sin(t*.7),jaw_open=8+8*math.sin(t*1.3))


def annotate(image,lines):
    draw=ImageDraw.Draw(image)
    try: font=ImageFont.truetype('C:/Windows/Fonts/msyh.ttc',16)
    except OSError: font=ImageFont.load_default()
    draw.rectangle((0,0,image.width,72),fill='#102435')
    for i,line in enumerate(lines[:3]):draw.text((12,5+i*22),line,font=font,fill='white')
    return image


class Viewer:
    def __init__(self,root,mode,camera_index=0,render_quality='fast',controller='illustrative'):
        import tkinter as tk
        from tkinter import ttk
        from PIL import ImageTk
        self.tk,self.ImageTk=tk,ImageTk
        self.root=root
        root.title('NeuroHead | PyBullet · Will Cogley模型 · AX7020只读')
        root.geometry('1300x900+30+30')
        root.minsize(1100,800)
        self.render_quality=render_quality if FAST_MODEL.exists() else 'detail'
        self.scene=HeadScene(gui=False,model=FAST_MODEL if self.render_quality=='fast' else MODEL)
        self.last_tick=None
        self.board=None
        self.vision=None
        self.camera_index=camera_index
        self.controller_name=controller
        self.gaze=VisualGaze()
        self.camera_photo=None
        self.replay=Replay()
        self.mode='manual'
        self.started=time.monotonic()
        self.closed=False
        self.error=''
        self.plot_rows=deque(maxlen=200)
        self.run_dir=ROOT/'data/pybullet_runs'/datetime.now().strftime('%Y%m%d_%H%M%S_%f')
        self.run_dir.mkdir(parents=True,exist_ok=True)
        self.log=(self.run_dir/'frames.jsonl').open('w',encoding='utf-8')
        ttk.Label(root,text='NeuroHead / PyBullet 三维工作台',font=('Microsoft YaHei',17,'bold')).pack(anchor='w',padx=16,pady=(12,3))
        top=ttk.Frame(root);top.pack(fill='x',padx=16,pady=6)
        self.buttons={}
        for index,(label,m) in enumerate([('视觉＋板卡只读','vision_board'),('摄像头跟随模型','vision'),('ViSP目标演示','visp_demo'),('三维动作演示','demo'),('手动模型','manual'),('真实AX7020只读','board'),('真实PL记录回放','replay')]):
            button=ttk.Button(top,text=label,command=lambda value=m:self.set_mode(value))
            button.grid(row=0,column=index,padx=4,pady=4,sticky='ew');self.buttons[m]=button
        ttk.Button(top,text='保存模型截图',command=self.snapshot).grid(row=0,column=7,padx=4,pady=4,sticky='ew')
        ttk.Button(top,text='导出实验报告',command=self.export_report).grid(row=0,column=8,padx=4,pady=4,sticky='ew')
        for column in range(9):top.columnconfigure(column,weight=1)
        render_bar=ttk.Frame(root);render_bar.pack(fill='x',padx=16,pady=(0,4))
        self.quality_text=tk.StringVar(value='流畅' if self.render_quality=='fast' else '精细')
        ttk.Label(render_bar,text='三维显示：').pack(side='left')
        quality=ttk.Combobox(render_bar,textvariable=self.quality_text,values=('流畅','精细'),state='readonly',width=7)
        quality.pack(side='left');quality.bind('<<ComboboxSelected>>',self.change_quality)
        self.controller_text=tk.StringVar(value='ViSP 原生' if controller=='visp' else '原虚拟映射')
        ttk.Label(render_bar,text='  视觉控制：').pack(side='left')
        controller_box=ttk.Combobox(render_bar,textvariable=self.controller_text,
                                  values=('ViSP 原生','原虚拟映射'),state='readonly',width=12)
        controller_box.pack(side='left');controller_box.bind('<<ComboboxSelected>>',self.change_controller)
        self.performance_text=tk.StringVar(value='正在准备模型')
        ttk.Label(render_bar,textvariable=self.performance_text).pack(side='left',padx=12)
        body=ttk.Frame(root);body.pack(fill='both',expand=True,padx=16)
        self.mode_text=tk.StringVar();self.state_text=tk.StringVar()
        left=ttk.Frame(body);left.pack(side='left',fill='both',expand=True)
        self.canvas=tk.Canvas(left,bg='#edf1f4',highlightthickness=0)
        self.canvas.pack(fill='both',expand=True)
        self.canvas.bind('<ButtonPress-1>',lambda e:setattr(self,'drag',(e.x,e.y)))
        self.canvas.bind('<B1-Motion>',self.rotate)
        self.canvas.bind('<MouseWheel>',self.zoom)
        ttk.Label(left,textvariable=self.mode_text,font=('Microsoft YaHei',11,'bold'),wraplength=850).pack(anchor='w',pady=5)
        right=ttk.Frame(body,width=305);right.pack(side='right',fill='y',padx=(14,0));right.pack_propagate(False)
        self.tabs=ttk.Notebook(right);self.tabs.pack(fill='both',expand=True)
        controls=ttk.Frame(self.tabs);camera_tab=ttk.Frame(self.tabs)
        self.tabs.add(controls,text='模型姿态');self.tabs.add(camera_tab,text='摄像头画面')
        self.camera_tab=camera_tab
        curves=ttk.Frame(self.tabs);self.tabs.add(curves,text='曲线/板卡')
        ttk.Label(curves,text='近20秒：青色=x，橙色=y').pack(anchor='w',pady=4)
        ttk.Label(curves,text='图像中心输入偏移（不是闭环误差）',wraplength=290).pack(anchor='w')
        self.input_plot=tk.Canvas(curves,height=130,bg='#102435',highlightthickness=0);self.input_plot.pack(fill='x',pady=4)
        ttk.Label(curves,text='虚拟眼＋头合成角（度，非实测）',wraplength=290).pack(anchor='w')
        self.angle_plot=tk.Canvas(curves,height=130,bg='#102435',highlightthickness=0);self.angle_plot.pack(fill='x',pady=4)
        self.board_text=tk.StringVar(value='板卡监测未启用')
        ttk.Label(curves,textvariable=self.board_text,wraplength=290).pack(anchor='w',pady=6)
        self.camera_view=ttk.Label(camera_tab,text='点击“摄像头跟随模型”打开外接摄像头',wraplength=290)
        self.camera_view.pack(anchor='center',pady=8)
        self.vision_text=tk.StringVar(value='摄像头尚未打开')
        ttk.Label(camera_tab,textvariable=self.vision_text,wraplength=290).pack(anchor='w',pady=8)
        ttk.Label(camera_tab,text='目标：画面最大的人脸中心。\n绿色框=检测；黄色线=输入中心偏移。\n角度只驱动虚拟模型；联合模式仅查询板卡。\n桌面摄像头映射未经外参标定。',wraplength=290).pack(anchor='w',pady=8)
        ttk.Label(controls,text='模型姿态 / 度（非实测）',font=('Microsoft YaHei',12,'bold')).pack(anchor='w',pady=(3,8))
        self.values,self.scales={},[]
        labels=('颈部左右','颈部俯仰','颈部侧倾','双眼左右','双眼上下','下颌张开')
        for key,label,limits in zip(POSE_KEYS,labels,[(-30,30),(-15,15),(-12,12),(-30,30),(-15,15),(0,18)]):
            var=tk.DoubleVar(value=0);self.values[key]=var
            ttk.Label(controls,text=label).pack(anchor='w')
            scale=tk.Scale(controls,from_=limits[0],to=limits[1],variable=var,orient='horizontal',resolution=.1,length=290)
            scale.pack(fill='x',pady=(0,5));self.scales.append(scale)
        ttk.Label(right,textvariable=self.state_text,wraplength=300,font=('Microsoft YaHei',10)).pack(anchor='w',pady=8)
        ttk.Label(root,text='原模型：Will Cogley Robot Head α2.0.33  |  直接拖动画面旋转、滚轮缩放  |  PyBullet软件渲染',font=('Microsoft YaHei',10)).pack(anchor='w',padx=16,pady=6)
        ttk.Label(root,text='近似运动学显示；未标定脉宽→角度。不能据此判断连杆碰撞、转矩或安全范围。无舵机控制命令。',foreground='#9c4618').pack(anchor='w',padx=16,pady=(0,10))
        root.protocol('WM_DELETE_WINDOW',self.close)
        self.last_image=None
        self.frame_count=0
        self.set_mode(mode)
        root.after(20,self.tick)

    def set_mode(self,mode):
        if self.board:self.board.close();self.board=None
        if self.vision:self.vision.close();self.vision=None
        self.mode,self.started,self.error=mode,time.monotonic(),''
        close_gaze(self.gaze)
        if mode=='visp_demo':
            self.controller_name='visp';self.controller_text.set('ViSP 原生')
        self.gaze=make_gaze(self.controller_name) if mode in ('vision','vision_board','visp_demo') else VisualGaze()
        if mode in ('vision','vision_board'):
            self.vision=VisionSource(self.camera_index).start()
            self.tabs.select(self.camera_tab)
        self.attach_gaze_source()
        if mode in ('board','vision_board'):self.board=ReadOnlyBoardMonitor()
        for scale in self.scales:scale.configure(state='normal' if mode=='manual' else 'disabled')
        for key,button in self.buttons.items():button.configure(state='disabled' if key==mode else 'normal')

    def change_controller(self,event=None):
        self.controller_name='visp' if self.controller_text.get()=='ViSP 原生' else 'illustrative'
        if self.mode=='visp_demo' and self.controller_name!='visp':
            self.set_mode('demo');return
        close_gaze(self.gaze)
        self.gaze=make_gaze(self.controller_name) if self.mode in ('vision','vision_board','visp_demo') else VisualGaze()
        self.attach_gaze_source()

    def attach_gaze_source(self):
        if not hasattr(self.gaze,'set_input_source'):return
        if self.mode in ('vision','vision_board'):
            source=self.vision
            self.gaze.set_input_source(lambda:source.snapshot()[0])
        elif self.mode=='visp_demo':
            started=self.started
            def sample():
                now=time.monotonic()
                return dict(target=synthetic_target(now-started),frame_time=now,running=True)
            self.gaze.set_input_source(sample)

    def rotate(self,event):
        if hasattr(self,'drag'):
            self.scene.yaw+=(event.x-self.drag[0])*.4
            self.scene.pitch=max(-65,min(65,self.scene.pitch+(event.y-self.drag[1])*.3))
        self.drag=(event.x,event.y)

    def zoom(self,event):self.scene.distance=max(.28,min(1,self.scene.distance-event.delta/120*.035))

    def change_quality(self,event=None):
        quality='fast' if self.quality_text.get()=='流畅' else 'detail'
        if quality==self.render_quality:return
        if quality=='fast' and not FAST_MODEL.exists():
            self.quality_text.set('精细');return
        view=(self.scene.yaw,self.scene.pitch,self.scene.distance)
        self.scene.close()
        self.scene=HeadScene(model=FAST_MODEL if quality=='fast' else MODEL)
        self.scene.yaw,self.scene.pitch,self.scene.distance=view
        self.render_quality=quality
        self.last_tick=None

    def tick(self):
        if self.closed:return
        if not p.isConnected(self.scene.client):self.close();return
        began=time.monotonic()
        began_perf=time.perf_counter()
        frame_period_ms=(began_perf-self.last_tick)*1000 if self.last_tick is not None else None
        self.last_tick=began_perf
        t=began-self.started
        state=None
        vision_packet=None
        model_target=None
        board_packet=self.board.snapshot() if self.board else {}
        if self.mode=='demo':
            pose=demo_pose(t);label='动作演示：仅模型运动，未连接硬件'
            detail='原装配外观 + 近似关节。演示角度不下发板卡。'
        elif self.mode=='visp_demo':
            model_target=synthetic_target(t)
            pose=self.gaze.step(model_target,began,began)
            label='ViSP 原生控制 → 虚拟目标；不使用摄像头或板卡'
            detail='输入为合成目标方位；vpServo计算两轴虚拟角速度。\n模型假设未经实物标定；不判断闭链连杆安全。'
        elif self.mode=='manual':
            pose={key:var.get() for key,var in self.values.items()};label='手动模型：滑块仅控制PyBullet'
            detail='本模式不发送任何网络数据。'
        elif self.mode=='replay':
            state=self.replay.at(t);pose=display_pose(state)
            label='真实PL历史回放（循环）；本轮现场反馈：没有动作'
            detail='画面是PL设置的示意换算，不能证明舵盘或眼球曾运动。'
        elif self.mode in ('vision','vision_board'):
            vision_packet,frame=self.vision.snapshot()
            valid_stream=vision_packet['running'] and not vision_packet['error']
            model_target=vision_packet['target'] if valid_stream else None
            pose=self.gaze.step(vision_packet['target'] if valid_stream else None,
                                vision_packet['frame_time'] if valid_stream else None,began)
            if frame is not None:
                preview=Image.fromarray(frame)
                preview.thumbnail((295,225))
                self.camera_photo=self.ImageTk.PhotoImage(preview)
                self.camera_view.configure(image=self.camera_photo,text='')
            labels=dict(tracking='检测到人脸，模型跟随',brief_target_loss='短暂丢失目标',
                        no_target='未检测到人脸，模型回正',camera_stale='等待摄像头或数据过期',waiting='等待摄像头',
                        controller_starting='ViSP正在启动',controller_stale='ViSP数据过期，模型保持',controller_error='ViSP错误，模型保持')
            label='真实摄像头 → '+('ViSP / ' if self.controller_name=='visp' else '')+'虚拟模型：'+labels[self.gaze.status]
            age=began-vision_packet['frame_time'] if vision_packet['frame_time'] is not None else None
            age_text=f'{age*1000:.0f} ms' if age is not None else '未取得'
            self.vision_text.set(f"设备索引：{self.camera_index}\n检测器：{vision_packet.get('detector','加载中')}\n已采集：{vision_packet['frame_id']}帧；人脸：{vision_packet['face_count']}\n主机帧龄（渲染前）：{age_text}\n状态：{vision_packet['error'] or labels[self.gaze.status]}")
            detail='仅模型眼头协同：眼睛先跟随，头部缓慢分担。目标丢失后逐渐回正。\n硬件动作命令：0；没有实际关节角度测量。'
            if self.mode=='vision_board':
                label+='；板卡'+('只读在线' if board_packet['fresh'] else '未回复/数据过期')
                detail+='\n板卡独立只读；虚拟角度没有发送到PL。'
        else:
            state=board_packet.get('state')
            pose=display_pose(state) if state else dict.fromkeys(POSE_KEYS,0)
            fresh=self.board is not None and self.board.fresh
            label='真实AX7020只读：'+('在线' if fresh else '离线或数据过期，姿态冻结/占位')
            detail=self.error or '仅NQ查询；颈部/下颌保持零位。两路映射到眼部示意，CH2未完成接线验证。'
        if self.mode!='manual':
            for key,var in self.values.items():var.set(round(pose[key],2))
        self.scene.pose(pose)
        render_started=time.perf_counter()
        width=min(960,max(400,self.canvas.winfo_width()))
        height=min(690,max(400,self.canvas.winfo_height()))
        ratio=min(1,640/width) if self.render_quality=='fast' else 1
        render_size=(max(1,round(width*ratio)),max(1,round(height*ratio)))
        self.last_image=self.scene.render(*render_size,shadows=self.render_quality=='detail')
        render_ms=(time.perf_counter()-render_started)*1000
        if self.last_image.size!=(width,height):
            self.last_image=self.last_image.resize((width,height),Image.Resampling.BILINEAR)
        refresh_text=f'{1000/frame_period_ms:.1f} 次/秒' if frame_period_ms else '预热中'
        self.performance_text.set(f'三维渲染 {render_ms:.0f} ms；窗口刷新 {refresh_text}（不是相机帧率）')
        self.photo=self.ImageTk.PhotoImage(self.last_image)
        self.canvas.delete('all')
        self.canvas.create_image(0,0,image=self.photo,anchor='nw')
        self.frame_count+=1
        if self.frame_count in (2,10):
            self.last_image.save(self.run_dir/f'canvas_frame_{self.frame_count:02d}.png')
            layout=dict(renderer='PyBullet TinyRenderer -> Tk PhotoImage',
                        frame=self.frame_count,render_ms=render_ms,
                        window_size=[self.root.winfo_width(),self.root.winfo_height()],
                        image_size=list(self.last_image.size),canvas_bbox=self.canvas.bbox('all'),
                        render_quality=self.render_quality,internal_render_size=render_size)
            (self.run_dir/'display_check.json').write_text(json.dumps(layout,indent=2),encoding='utf-8')
        self.mode_text.set(label)
        controller_packet=gaze_diagnostics(self.gaze)
        if controller_packet.get('backend')=='visp_native':
            metrics=controller_packet.get('metrics') or {}
            residual=metrics.get('virtual_error_norm')
            detail+=f"\nViSP原生计算：{metrics.get('native_compute_calls',0)}次；状态：{self.gaze.status}"
            if residual is not None:detail+=f'\n虚拟相机误差范数：{residual:.4f}（非实物误差）'
            if controller_packet.get('error'):detail+='\n'+controller_packet['error']
        if state:
            detail+=f"\nPL输出设置：{state['output_yaw_us']} / {state['output_pitch_us']} μs\n接受：{state['accepted']}  拒绝：{state['invalid']}\n看门狗事件累计：{state['watchdog_events']}\n显示换算：1000 μs→60°，未经实物标定。"
        if self.board:detail+=f'\n查询/回复：{self.board.queries}/{self.board.replies}；动作命令：0'
        self.state_text.set(detail)
        if self.board:
            s=board_packet.get('state') or {}
            self.board_text.set(f"AX7020：{'在线' if board_packet['fresh'] else '未回复/过期'}\n只读查询/回复：{board_packet['queries']}/{board_packet['replies']}\nPL设置：{s.get('output_yaw_us','--')} / {s.get('output_pitch_us','--')} μs\n看门狗累计：{s.get('watchdog_events','--')}\n{board_packet['error']}\n虚拟姿态与PL回读为独立数据源。")
        else:self.board_text.set('板卡监测未启用；曲线只表示虚拟模型。')
        target=model_target
        self.plot_rows.append((began,target,pose['eye_pan']+pose['neck_pan'],pose['eye_tilt']+pose['neck_tilt']))
        self.draw_curves(began)
        row=dict(mode=self.mode,elapsed_s=t,model_degrees=pose,state=state,
                 hardware_motion_commands_sent=0,angles_measured=False,render_ms=render_ms,
                 host_monotonic_s=began,board_monitor=board_packet,
                 frame_period_ms=frame_period_ms,render_quality=self.render_quality,
                 internal_render_size=render_size,
                 vision=vision_packet,gaze_status=self.gaze.status if self.mode in ('vision','vision_board','visp_demo') else None,
                 controller=self.controller_name,controller_diagnostics=controller_packet,
                 synthetic_target=model_target if self.mode=='visp_demo' else None)
        self.log.write(json.dumps(row,ensure_ascii=False)+'\n');self.log.flush()
        target_period=100 if self.render_quality=='fast' else 140
        self.root.after(max(5,int(target_period-(time.monotonic()-began)*1000)),self.tick)

    def draw_curves(self,now):
        rows=[r for r in self.plot_rows if now-r[0]<=20]
        for canvas,limit,source in ((self.input_plot,1,'input'),(self.angle_plot,45,'angle')):
            canvas.delete('all');width=max(100,canvas.winfo_width());height=130
            canvas.create_line(28,height/2,width,height/2,fill='#71818e')
            canvas.create_text(14,12,text=str(limit),fill='white',font=('Arial',8))
            canvas.create_text(14,height-12,text=str(-limit),fill='white',font=('Arial',8))
            for channel,color in enumerate(('#41d7db','#ffb150')):
                previous=None
                for stamp,target,pan,tilt in rows:
                    value=(target[channel] if target is not None else None) if source=='input' else (pan,tilt)[channel]
                    if value is None:previous=None;continue
                    point=(28+(stamp-(now-20))/20*(width-30),height/2-max(-limit,min(limit,value))/limit*(height/2-12))
                    if previous:canvas.create_line(*previous,*point,fill=color,width=2)
                    previous=point

    def export_report(self):
        self.log.flush()
        path,_=export_session(self.run_dir)
        self.mode_text.set('实验报告已导出：'+str(path))

    def snapshot(self):
        image=annotate(self.scene.render(1200,850),[self.mode_text.get(),'模型姿态非实测角度；本窗口动作命令数=0'])
        path=self.run_dir/f'{datetime.now():%H%M%S_%f}_{self.mode}.png'
        image.save(path)
        self.mode_text.set('截图已保存：'+str(path.name))

    def close(self):
        self.closed=True
        if self.board:self.board.close()
        if self.vision:self.vision.close()
        close_gaze(self.gaze)
        self.log.close()
        export_session(self.run_dir)
        if p.isConnected(self.scene.client):self.scene.close()
        self.root.destroy()


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--mode',choices=('demo','manual','board','replay','vision','vision_board','visp_demo'),default='demo')
    parser.add_argument('--camera',type=int,default=0)
    parser.add_argument('--render-quality',choices=('fast','detail'),default='fast')
    parser.add_argument('--controller',choices=('illustrative','visp'),default='illustrative')
    parser.add_argument('--headless',action='store_true')
    parser.add_argument('--duration',type=float,default=3)
    parser.add_argument('--snapshot',type=Path,default=ROOT/'build/verification/pybullet_preview.png')
    args=parser.parse_args()
    if not MODEL.exists():parser.error('Run build/scripts/prepare_pybullet_head.py first')
    if not args.headless:
        import tkinter as tk
        root=tk.Tk();Viewer(root,args.mode,args.camera,args.render_quality,args.controller);root.mainloop();return
    if not 0<args.duration<=30:parser.error('duration must be 0..30 seconds')
    scene=HeadScene(model=FAST_MODEL if args.render_quality=='fast' and FAST_MODEL.exists() else MODEL)
    board=None;vision=None;rows=[];gaze=make_gaze('visp' if args.mode=='visp_demo' else args.controller)
    try:
        if args.mode in ('board','vision_board'):board=ReadOnlyBoardMonitor()
        if args.mode in ('vision','vision_board'):vision=VisionSource(args.camera).start()
        replay=Replay() if args.mode=='replay' else None
        started=time.monotonic()
        while time.monotonic()-started<args.duration:
            now=time.monotonic()
            board_packet=board.snapshot() if board else {}
            state=board_packet.get('state') if board else replay.at(now-started) if replay else None
            vision_packet=None
            if args.mode=='visp_demo':
                pose=gaze.step(synthetic_target(now-started),now,now)
            elif vision:
                vision_packet,_=vision.snapshot()
                stream_ok=vision_packet['running'] and not vision_packet['error']
                pose=gaze.step(vision_packet['target'] if stream_ok else None,
                               vision_packet['frame_time'] if stream_ok else None,time.monotonic())
            else:
                pose=display_pose(state) if state else demo_pose(time.monotonic()-started) if args.mode=='demo' else dict.fromkeys(POSE_KEYS,0)
            scene.pose(pose)
            rows.append(dict(mode=args.mode,host_monotonic_s=now,state=state,model_degrees=pose,
                             vision=vision_packet,board_monitor=board_packet,
                             gaze_status=gaze.status if vision or args.mode=='visp_demo' else None,
                             controller_diagnostics=gaze_diagnostics(gaze),
                             hardware_motion_commands_sent=0,angles_measured=False))
            time.sleep(.03)
        fresh_at_capture=board.fresh if board else None
        image=scene.render(1200,850)
        args.snapshot.parent.mkdir(parents=True,exist_ok=True)
        annotate(image,[f'PyBullet / {args.mode} / Will Cogley reference geometry',
                        '示意姿态非实测角度；无舵机控制命令']).save(args.snapshot)
        report=dict(mode=args.mode,hardware_motion_commands_sent=0,angles_measured=False,
                    render_quality=args.render_quality if FAST_MODEL.exists() else 'detail',
                    queries=board.queries if board else 0,replies=board.replies if board else 0,
                    source_fresh=fresh_at_capture,final_state=board.state if board else None,
                    rendered_joints=len(scene.joints),samples=rows,snapshot=str(args.snapshot))
        if vision:
            report['vision_final']=vision.snapshot()[0]
            report['camera_images_saved']=0
            report['face_positive_observed']=any(row['vision']['face_count']>0 for row in rows)
        report['board_monitor_final']=board.snapshot() if board else None
        args.snapshot.with_suffix('.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
        print(json.dumps({k:v for k,v in report.items() if k!='samples'},indent=2))
    finally:
        if board:board.close()
        if vision:vision.close()
        close_gaze(gaze)
        scene.close()


if __name__=='__main__':main()
