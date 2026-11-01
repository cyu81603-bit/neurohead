"""Teammate UI with the current conversation and sole-owner control backend."""
import argparse, json, os, queue, threading, time
from pathlib import Path
from types import SimpleNamespace as NS
import tkinter as tk
import customtkinter as ctk
from embodied_app import BrainPanel, HERE, PROJECT
from teammate_layout import TeammateLayout
from intent_link import IntentLink

class TeammatePanel(ctk.CTkToplevel, BrainPanel, TeammateLayout):
    def __init__(self, parent, controller, services=True, listen=False):
        ctk.set_appearance_mode('Dark')
        ctk.CTkToplevel.__init__(self, parent)
        self.window=self; self.controller=controller; self.speech_only=False
        self.events=queue.Queue(); self.closed=threading.Event()
        self.query_lock=threading.Lock(); self.generation=0
        self.intent_generation_lock=threading.RLock()
        self.link=IntentLink(controller.control)
        self.brain=self.voice=self.speech=self.buffer=self.frame=None
        self.vision={}; self.last_key=None; self.poll_id=None
        self.auto_listen=False; self.last_status_write=0.
        self.status=tk.StringVar(value='正在准备本地对话；麦克风关闭')
        self.channel_bars={}; self.channel_val_labels={}
        self.is_running=True
        cfg=json.loads((PROJECT/'config/lifelike_v6.json').read_text(encoding='utf-8-sig'))
        poses={p['channel']:p for p in cfg['poses']}
        channels=json.loads((PROJECT/'config/channels.json').read_text(encoding='utf-8-sig'))['channels']
        groups=lambda n: 'eye' if n<2 else 'brow' if n<6 else 'eyelid' if n<10 else 'lip' if n<14 else 'cheek' if n<18 else 'neck' if n<21 else 'jaw'
        specs=[]
        for row in channels:
            n=row['channel']; pose=poses.get(n,{})
            specs.append(NS(channel=n,j10_pin=row['signal_pin'],label=pose.get('label',row['joint']),group=groups(n),
                enabled=bool(pose.get('enabled',False)),probe_only=bool(pose.get('probe_only',False)),
                min_us=pose.get('min_us',row.get('min_us')) or 1000,max_us=pose.get('max_us',row.get('max_us')) or 2000,
                neutral_us=pose.get('neutral_us') or row.get('neutral_us') or (1270 if n==19 else 1500),action_us=pose.get('action_us')))
        self.nh22_runtime=NS(converter=NS(registry=NS(channels=specs)),trigger_blink=self._blink)
        self._build_ui()
        self.title('具身智能全链路主控台 · 同学原界面 / 并发对话R6.7')
        self.geometry('%dx%d+10+20'%(min(1680,self.winfo_screenwidth()-60),min(940,self.winfo_screenheight()-90))); self.minsize(1280,760)
        self.sw_hw_udp.configure(text='打开 USB Cam 共享预览')
        self.sw_http_bridge.configure(text='语音 / 表情联动')
        self.btn_mic_toggle.configure(text='语音监听：关')
        ctk.CTkButton(self.btn_send.master,text='测试播报',width=76,height=28,command=self.test_speaker).grid(row=0,column=2,padx=(5,0))
        ctk.CTkButton(self.sw_hw_udp.master,text='视觉处理流程',width=100,command=self.open_vision_dashboard).pack(side='right',padx=8)
        self.seg_neck.configure(state='disabled'); self.seg_style.configure(state='disabled')
        self.lbl_noise_gate.configure(text='自适应语音门限：')
        self.slider_noise_gate.configure(state='disabled')
        self.lbl_ctx_badge.configure(text='本地上下文 4096 tokens')
        self.lbl_mask_badge.configure(text='主控空闲 / PWM未开启')
        self.lbl_nh_hex.configure(text='唯一发送者：现有眼颈主控；本界面只发送语音与表情意图')
        self.lbl_live_video.configure(text='点击顶部打开 USB Cam；不会使用内置相机')
        self.txt_char_table.insert('end','等待实际语音合成结果；不显示模拟振幅。')
        self.bind('<Escape>',lambda e:self.interrupt())
        self.protocol('WM_DELETE_WINDOW',self.keep_window)
        self._log('已保留交接包原三栏布局；采用现有对话引擎和单一舵机控制器。')
        if services: threading.Thread(target=self.prepare,daemon=True,name='prepare-teammate-dialogue').start()
        self.poll_id=self.after(80,self.poll)

    def open_vision_dashboard(self):
        import subprocess
        script=PROJECT/'integration/vision_dashboard/start_dashboard.ps1'
        subprocess.Popen(['powershell.exe','-NoProfile','-ExecutionPolicy','Bypass','-File',str(script)],cwd=PROJECT,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))

    def _log(self,msg):
        self.txt_log.insert('end',time.strftime('[%H:%M:%S] ')+str(msg)+'\n'); self.txt_log.see('end')
    def _on_toggle_hw_udp(self):
        self.sw_hw_udp.deselect()
        self.controller.open_camera()
    def _on_toggle_http_bridge(self):
        try:
            if self.sw_http_bridge.get(): self.enable_link()
            else: self.disable_link()
        except Exception as exc: self.status.set(str(exc))
        if not self.link.enabled:self.sw_http_bridge.deselect()
        self._log(self.status.get())
    def _on_style_change(self,val):pass
    def _on_neck_speed_change(self,val):pass
    def _on_noise_gate_slider_change(self,val):pass
    def _blink(self):self._log('眨眼仍待方向和相机视野确认，请使用主控中的调试入口。')
    def _trigger_instant_demo(self,key):
        try:
            if not self.link.enabled:raise ValueError('先在原舵机主控开始会话、开启表情，再打开本窗口语音 / 表情联动')
            if key not in ('smile','sad','wink','neutral'):raise ValueError('未知表情')
            self.controller.control.life_event(dict(type='expression',name=key,duration_s=3,intensity=.8))
            self._log('触发表情：'+key+'；眼颈追踪保持，语音嘴形继续。')
        except Exception as exc:self._log(exc)
    def _open_wink_setup(self):
        setup=getattr(self.controller,'open_wink_setup',None)
        if setup:setup()
        else:self._log('请在机器人本机的表情调试窗口确认右眼 wink。')
    def _open_action_library(self):
        setup=getattr(self.controller,'open_action_library',None)
        if setup:setup()
        else:self._log('请在本机舵机操作面板打开动作库；远程语义窗口不能自行开启硬件。')
    def _toggle_mic(self):self.toggle_mic()
    def _interrupt_all(self,reason):self.interrupt()
    def _on_send_text_click(self):self.ask_text()
    def ask_text(self):
        text=self.entry_query.get().strip()
        if text:self.entry_query.delete(0,'end');self._trigger_manual_query(text)
    def _trigger_manual_query(self,text):
        self.event('heard',text);now=time.monotonic()
        threading.Thread(target=self.query,args=(text,now,now),daemon=True).start()
    def _clear_brain_context(self):
        if self.query_lock.locked():self._log('正在回答，请先打断并等待完成');return
        if self.brain:self.brain.clear_history()
        self._log('已清理会话记忆')

    def poll(self):
        from PIL import Image,ImageTk
        while True:
            try:kind,value=self.events.get_nowait()
            except queue.Empty:break
            if kind=='frame':
                rgb=Image.fromarray(value[:,:,::-1]);rgb.thumbnail((560,340))
                self.photo=ImageTk.PhotoImage(rgb)
                self.lbl_live_video.configure(image=self.photo,text='')
            elif kind=='camera_error':self.lbl_live_video.configure(image='',text=str(value))
            elif kind=='heard':self._log('你：'+value)
            elif kind=='reply':
                self._log('机器人：'+value['reply_text'])
                self.lbl_expr_badge.configure(text='当前表情：'+value.get('expression_label','无'))
                self._log(('本地模型' if value.get('backend')=='ollama' else '离线兜底')+' / %.1f秒'%(value['latency_ms']/1000))
            elif kind=='action_decision':
                from action_library import CATALOG
                chosen=value.get('actions',[]);dispatch=value.get('action_dispatch',{})
                self._log('模型动作决策：'+(' → '.join(CATALOG[n]['label'] for n in chosen) if chosen else '不激活动作库')+'；'+str(value.get('action_reason','')))
                if value.get('action_parse_error'):self._log('未执行：'+value['action_parse_error'])
                elif dispatch.get('status')=='rejected':self._log('未执行：'+str(dispatch.get('error','')))
                elif dispatch.get('status')=='accepted':self._log('动作请求已入队，执行结果见下方状态。')
            elif kind=='busy':self.btn_send.configure(state='disabled' if self.query_lock.locked() else 'normal')
            elif kind=='tts':
                self.txt_char_table.delete('1.0','end')
                self.txt_char_table.insert('end','实际合成 %d 字 / %.2f 秒\n'%(value['characters'],value['duration_s']))
                for r in value.get('records',[]):self.txt_char_table.insert('end',json.dumps(r,ensure_ascii=False)+'\n')
            elif kind=='tts_cursor':
                e=value['energy'];self.bar_lip_energy.set(e);self.lbl_lip_energy.configure(text='%.2f'%e)
                self.lbl_active_char.configure(text='播放 %.2fs | 音量包络 %.2f'%(value['time_ms']/1000,e))
            elif kind=='tts_done':
                if self.voice:self.voice.notify_tts_stopped()
                self.bar_lip_energy.set(0);self.lbl_lip_energy.configure(text='0.00')
            elif kind in ('error','ready','asr','link_warning'):
                self.status.set(str(value));self._log(value)
        self.lbl_asr_status.configure(text=self.status.get())
        self.btn_mic_toggle.configure(text='语音监听：'+('开' if self.voice and self.voice.is_enabled else '关'))
        self.lbl_mic_rms.configure(text='音量 %.0f / 底噪 %.0f'%(self.voice.current_rms,self.voice.gate.noise) if self.voice else '等待语音引擎')
        state=self.controller.snapshot() if hasattr(self.controller,'snapshot') else self.controller.control.extra
        state=state or {}
        current=state.get('action_active') or {};last=state.get('action_last') or {}
        action_summary=json.dumps(dict(active=current.get('name'),phase=(current.get('progress') or {}).get('phase'),last=last),ensure_ascii=False)
        if action_summary!=getattr(self,'_last_action_summary',None):
            self._last_action_summary=action_summary
            from action_library import describe_action
            if current:self._log('动作执行中：'+describe_action(current))
            elif last:self._log('动作状态：'+describe_action(last=last))
        self.lbl_mask_badge.configure(text='主控 '+str(state.get('mode','idle'))+' / 表情联动 '+('开' if self.link.enabled else '关'))
        if state.get('life_state') not in ('warming','active'):
            self.lbl_nh_hex.configure(text='表情模式未开启：可正常语音对话；眼颈追踪继续由原主控负责。')
        else:
            self.lbl_nh_hex.configure(text='表情模式已就绪；语音/表情联动开关由操作者手动开启。')
        self._render_telemetry(state)
        if self.buffer:
            bs=self.buffer.get_status()
            self.bar_buffer_span.set(min(1,bs.get('span_seconds',0)/5))
            self.lbl_buffer_badge.configure(text='共享视频池: %d 帧'%bs.get('frame_count',0))
            board=getattr(self.buffer,'_last_extracted_storyboard',None)
            if board is not None and id(board)!=getattr(self,'_story_id',None):
                self._story_id=id(board);rgb=Image.fromarray(board[:,:,::-1]);rgb.thumbnail((560,260))
                self.story_photo=ImageTk.PhotoImage(rgb);self.lbl_storyboard_img.configure(image=self.story_photo,text='')
        if time.monotonic()-self.last_status_write>1:
            self.last_status_write=time.monotonic()
            status=dict(pid=os.getpid(),updated=time.time(),ready=self.brain is not None,ui='teammate_original',audio_revision=2,
                microphone_enabled=bool(self.voice and self.voice.is_enabled),linked=self.link.enabled)
            dest=HERE/'build/teammate_ui_audio2_status.json';dest.parent.mkdir(exist_ok=True)
            tmp=dest.with_suffix('.tmp');tmp.write_text(json.dumps(status),encoding='utf-8');os.replace(tmp,dest)
        self.poll_id=self.after(80,self.poll)

    def _render_telemetry(self,state):
        # Only show values actually reported by the existing controller.
        values=state.get('all_output_pwm_us')
        local=getattr(self.controller.control,'last_state',None)
        if isinstance(local,dict):values=local.get('output_us',values)
        for container in (state,state.get('last_state',{}),state.get('telemetry',{})):
            if isinstance(container,dict) and isinstance(container.get('output_us'),list):values=container['output_us'];break
        for n,label in self.channel_val_labels.items():
            if values and len(values)==22:
                label.configure(text='%4d us'%values[n]);self.channel_bars[n].set(max(0,min(1,(values[n]-600)/1800)))
            elif len(state.get('output_pwm_us',[]))==5 and n in (0,1,18,19,20) and state.get('mode')=='running':
                v=state['output_pwm_us'][(0,1,18,19,20).index(n)]
                label.configure(text='%4d us'%v);self.channel_bars[n].set(max(0,min(1,(v-600)/1800)))
            else:label.configure(text='-- us');self.channel_bars[n].set(0)
        self.lbl_buf_detail.configure(text='共享 USB Cam / '+('已收到画面' if self.frame is not None else '等待画面'))


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--self-test',action='store_true');args=parser.parse_args()
    from remote_controller import RemoteController
    ctk.set_appearance_mode('Dark');ctk.set_default_color_theme('blue')
    root=ctk.CTk();root.withdraw();panel=TeammatePanel(root,RemoteController(),services=not args.self_test)
    if args.self_test:
        root.update();assert panel.voice is None and panel.brain is None and not panel.link.enabled
        assert len(panel.channel_val_labels)==22
        panel.shutdown();panel.destroy();root.destroy();print('TEAMMATE_LAYOUT_IDLE_NO_CAMERA_NO_MIC_NO_HARDWARE_PASS')
    else:root.mainloop()
if __name__=='__main__':main()
