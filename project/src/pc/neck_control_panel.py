"""Neck commissioning v2. Default idle, independent live rod polarities."""
import argparse,json,os,time,tkinter as tk
from neck_control import NeckControl,ROOT
from neck_session import NeckSession
from neck_coordinates import pose_to_pwm,pose_to_logical
from neck_presets import rod_up_signs,rod_preset,rod_shift,neck_neutral,side_preset_limit,side_amplitudes
from runtime_logs import write_status
class Panel:
    def __init__(self,window,controller_factory=NeckSession):
        self.window=window;self.profile_path=ROOT/'config/neck_follow.json'
        self.control=controller_factory(json.loads(self.profile_path.read_text(encoding='utf-8-sig')))
        self.runtime_path=ROOT/'build'/('neck_manual_runtime_'+str(os.getpid())+'.json')
        self.last=time.monotonic();self.last_status=0.;self.last_profile=0.;self.signs=None;self.syncing=False
        self.demo=None;self.demo_result=None;self.reference=neck_neutral(self.control.profile);self.user_target_changed=False
        self.position_mode=tk.StringVar(master=window,value='logical')
        self.side_span_vars={k:tk.StringVar(master=window,value='170') for k in ('left_up_right_down','left_down_right_up')}
        self.side_spans={};self.saved_side_spans=None;self.side_limit=0;self.side_limit_text=tk.StringVar(master=window,value='')
        window.title('NeuroHead 颈部联调 v5 · 中位与双向幅度标定')
        window.geometry('960x820');window.resizable(False,False)
        tk.Label(window,text='颈部三路机械联调 v5',font=('Microsoft YaHei UI',21,'bold')).pack(pady=(16,6))
        tk.Label(window,text='仅颈部：Pin21左右、Pin22左杆、Pin23右杆。眼部不启用。',font=('Microsoft YaHei UI',11)).pack()
        tk.Label(window,text='逻辑位置1500＝各轴标定中位；实际PWM仍限1100–1900μs、100μs/s。开始前请托稳。',font=('Microsoft YaHei UI',10)).pack(pady=5)
        self.message=tk.StringVar(value='新窗口尚未发指令。旧窗口若异常占用，请先结束旧会话再在本窗开始。')
        self.readback=tk.StringVar(value='尚未连接板卡')
        self.reference_display=tk.StringVar(value='')
        self.direction=tk.StringVar(value='升降极性正在读取')
        mode_row=tk.Frame(window);mode_row.pack(pady=4)
        for title,mode in (('逻辑位置（中位统一1500）','logical'),('实际PWM（μs）','physical')):
            tk.Radiobutton(mode_row,text=title,variable=self.position_mode,value=mode,command=self.switch_mode).pack(side='left',padx=12)
        self.scales=[];self.axis_labels=[]
        for title in ('左右转头 · Pin21','机器人左杆 · Pin22','机器人右杆 · Pin23'):
            frame=tk.Frame(window);frame.pack(pady=3)
            label=tk.Label(frame,text=title,width=37,anchor='w',font=('Microsoft YaHei UI',10));label.pack(side='left');self.axis_labels.append(label)
            slider=tk.Scale(frame,from_=1100,to=1900,resolution=1,orient='horizontal',length=400)
            slider.set(1500);slider.pack(side='left');self.scales.append(slider)
        for slider in self.scales:slider.configure(command=self.changed)
        tk.Label(window,textvariable=self.reference_display,font=('Microsoft YaHei UI',11)).pack(pady=3)
        tk.Label(window,textvariable=self.direction,font=('Microsoft YaHei UI',10)).pack(pady=4)
        row=tk.Frame(window);row.pack(pady=8);self.mapping_buttons=[]
        for title,callback in (('两杆升50',lambda:self.shift(50)),('两杆降50',lambda:self.shift(-50)),
            ('左升右降',lambda:self.physical_preset(1,-1)),('左降右升',lambda:self.physical_preset(-1,1))):
            b=tk.Button(row,text=title,width=14,command=callback,state='disabled');b.pack(side='left',padx=4);self.mapping_buttons.append(b)
        tk.Button(row,text='回中',width=10,command=self.home).pack(side='left',padx=4)
        amp_row=tk.Frame(window);amp_row.pack(pady=5);self.side_span_spins=[]
        for title,key in (('左升右降幅度','left_up_right_down'),('左降右升幅度','left_down_right_up')):
            tk.Label(amp_row,text=title).pack(side='left',padx=4)
            spin=tk.Spinbox(amp_row,from_=0,to=400,increment=10,width=6,textvariable=self.side_span_vars[key])
            spin.pack(side='left',padx=4);self.side_span_spins.append(spin)
        tk.Button(amp_row,text='保存组合幅度',command=self.save_side_spans,width=17).pack(side='left',padx=8)
        tk.Label(window,textvariable=self.side_limit_text,font=('Microsoft YaHei UI',10)).pack(pady=1)
        row=tk.Frame(window);row.pack(pady=12)
        tk.Button(row,text='开始／继续',width=16,command=self.start).pack(side='left',padx=6)
        tk.Button(row,text='暂停并保持',width=16,command=self.pause).pack(side='left',padx=6)
        tk.Button(row,text='已托稳，结束停PWM',width=24,command=self.end).pack(side='left',padx=6)
        self.demo_button=tk.Button(window,text='按已确认升降方向连续试运行，结束后保持中位',width=54,command=self.begin_demo,state='disabled')
        self.demo_button.pack(pady=5)
        tk.Button(window,text='暂停并将当前PWM回读设为标定中位',width=48,command=self.save_reference).pack(pady=3)
        tk.Label(window,textvariable=self.readback,font=('Microsoft YaHei UI',12)).pack(pady=10)
        tk.Label(window,textvariable=self.message,font=('Microsoft YaHei UI',11),wraplength=820).pack(pady=6)
        tk.Label(window,text='暂停保留PWM；异常保留已配置断流保持。若顶住，托稳后使用结束停PWM。',font=('Microsoft YaHei UI',10)).pack(pady=5)
        self.refresh_mapping();window.protocol('WM_DELETE_WINDOW',self.close);window.after(50,self.poll)
    def values(self):
        shown=[int(s.get()) for s in self.scales]
        return pose_to_pwm(shown,self.control.profile) if self.position_mode.get()=='logical' else shown
    def switch_mode(self):
        # A view change only redraws the same hardware target.
        self.sync(self.control.desired)
    def sync(self,values):
        self.syncing=True
        shown=pose_to_logical(values,self.control.profile) if self.position_mode.get()=='logical' else values
        for s,u in zip(self.scales,shown):s.set(u)
        self.syncing=False
    def refresh_mapping(self):
        old_reference=list(self.reference)
        try:
            profile=json.loads(self.profile_path.read_text(encoding='utf-8-sig'))
            reference=neck_neutral(profile);self.control.profile=profile;self.reference=reference
            signs=rod_up_signs(profile)
        except (OSError,ValueError):signs=None
        self.signs=signs
        try:
            self.side_limit=side_preset_limit(self.control.profile);self.side_spans=side_amplitudes(self.control.profile)
            if self.side_spans!=self.saved_side_spans:
                for key,value in self.side_spans.items():self.side_span_vars[key].set(str(value))
                self.saved_side_spans=dict(self.side_spans)
            for spin in self.side_span_spins:spin.configure(to=self.side_limit)
            self.side_limit_text.set('组合幅度为实际PWM偏移；当前双向共同范围0–%dμs，可分别调小微调。'%self.side_limit)
        except ValueError:self.side_limit_text.set('组合幅度配置需要复核，暂勿使用组合按钮。')
        if self.reference!=old_reference:self.sync(self.control.desired)
        self.reference_display.set('实际标定中位PWM：Pin21=%d，Pin22=%d，Pin23=%d'%tuple(self.reference))
        if self.control.mode=='idle' and not self.user_target_changed:
            self.sync(self.reference);self.control.set_targets(self.reference)
        for b in self.mapping_buttons+[self.demo_button]:b.configure(state='normal' if signs else 'disabled')
        self.direction.set('已确认升降极性：左%s、右%s（+表示增大PWM升杆）'%signs if signs else '升降方向存在冲突，组合按钮暂不启用；原始PWM滑块可用于复核。')
        for i,name in ((1,'机器人左杆 · Pin22'),(2,'机器人右杆 · Pin23')):
            detail='方向待复核' if signs is None else '数值增大'+('升杆' if signs[i-1]>0 else '降杆')
            self.axis_labels[i].configure(text=name+'（'+detail+'）')
    def changed(self,_=None):
        if self.syncing:return
        self.demo=None;self.user_target_changed=True
        try:self.control.set_targets(self.values())
        except Exception as exc:self.message.set(str(exc))
    def preset(self,values):
        self.demo=None;self.user_target_changed=True;self.sync(values);self.control.set_targets(values)
        if self.control.mode=='paused':self.message.set('目标已暂存；点击继续后低速移动，当前仍保持。')
    def physical_preset(self,left_up,right_up):
        self.refresh_mapping()
        try:self.preset(rod_preset(self.values()[0],left_up,right_up,self.control.profile))
        except ValueError as exc:self.message.set(str(exc))
    def shift(self,amount):
        self.refresh_mapping()
        try:self.preset(rod_shift(self.values(),amount,self.control.profile))
        except ValueError as exc:self.message.set(str(exc))
    def home(self):
        self.refresh_mapping();self.preset(self.reference)
    def save_reference(self):
        if self.control.mode not in ('running','paused') or self.control.last_state is None:
            self.message.set('需要正常运行且有PWM回读；异常或未连接时不能记录中位。');return
        self.pause();values=list(self.control.output)
        profile=json.loads(self.profile_path.read_text(encoding='utf-8-sig'))
        profile.update(manual_neck_reference_us=values,pair_reference_us=values[1:],yaw_reference_pulse_us=values[0],
            manual_reference_method='operator_recorded_paused_PWM_readback_not_angle_measurement')
        write_status(self.profile_path,profile);self.refresh_mapping();self.sync(values)
        self.message.set('已将当前PWM回读记录为标定中位，当前位置保持不变；下次回中或启动使用新值。')
    def save_side_spans(self):
        try:
            profile=json.loads(self.profile_path.read_text(encoding='utf-8-sig'));limit=side_preset_limit(profile)
            values={key:int(var.get()) for key,var in self.side_span_vars.items()}
            if any(not 0<=v<=limit for v in values.values()):raise ValueError('当前两方向共同安全幅度为0–%dμs'%limit)
            profile.update(side_presets_balanced=True,side_preset_spans_us=values)
            write_status(self.profile_path,profile);self.refresh_mapping()
            self.message.set('组合幅度已保存，当前位置不变；下次点击组合或试运行使用新幅度。')
        except (ValueError,OSError) as exc:self.message.set('未保存：'+str(exc))
    def start(self):
        try:
            self.refresh_mapping();self.control.set_targets(self.values());self.control.start();self.last=time.monotonic()
            self.message.set('运行中。回中及组合使用各轴独立标定值。')
        except Exception as exc:self.message.set('未开始：'+str(exc))
    def pause(self):
        if self.control.mode=='idle':self.message.set('本窗口未运行，没有保持PWM。');return
        self.demo=None;self.control.pause();self.sync(self.control.output)
        self.message.set('已暂停，继续保持当前位置。' if self.control.mode=='paused' else '异常会话保留，请托稳后结束并重新核对状态。')
    def snapshot(self):
        state=self.control.last_state or {}
        return dict(mode=self.control.mode,updated_epoch=time.time(),owner_pid=os.getpid(),
            desired_us=self.control.desired,output_pwm_us=self.control.output,eyes_active=False,reference_us=self.reference,configured_reference_us=self.control.reference,
            transport_error=self.control.error,board_status=state.get('status'),board_active_mask=state.get('active_mask'),
            board_sequence=state.get('sequence'),rod_up_pwm_signs=self.signs,demo_running=self.demo is not None,
            input_mode=self.position_mode.get(),logical_desired=pose_to_logical(self.control.desired,self.control.profile),
            worker_max_gap_s=getattr(self.control,'max_active_gap_s',None),side_preset_spans_us=self.side_spans,side_preset_limit_us=self.side_limit)
    def end(self):
        if self.control.mode=='idle':self.message.set('本窗口没有控制会话，未发送停止指令。');return
        self.demo=None
        try:
            self.control.end(head_supported=True)
            self.sync(self.reference);self.control.set_targets(self.reference);self.user_target_changed=False
            write_status(ROOT/'build/neck_manual_active.json',self.snapshot())
            self.message.set('已由板卡确认PWM关闭；旧停止应答丢失也可通过状态查询恢复。窗口保留。')
        except Exception as exc:self.message.set('停止状态仍未确认：'+str(exc)+'；保持头部支撑。')
    def begin_demo(self):
        self.refresh_mapping()
        if self.signs is None:return
        if self.control.mode=='fault':self.message.set('请先托稳并结束异常会话。');return
        p=self.control.profile
        reference=neck_neutral(p);yaw=reference[0]
        poses=[('中位稳定',reference,3),('左杆升、右杆降',rod_preset(yaw,1,-1,p),6),
            ('回中保持',reference,6),('左杆降、右杆升',rod_preset(yaw,-1,1,p),6),('回中保持',reference,6)]
        self.sync(reference);self.control.set_targets(reference);self.start()
        if self.control.mode!='running':return
        path=ROOT/'build'/('neck_manual_v2_demo_'+str(time.time_ns())+'.result.json')
        self.demo=dict(index=0,phase_start=time.monotonic(),phases=poses,path=path)
        self.demo_result=dict(purpose='polarity_aware_neck_demo',eyes_active=False,physical_observation=None,phase_endpoints=[])
    def demo_tick(self,now):
        if self.demo is None:return
        if self.control.mode!='running':self.demo=None;return
        i=self.demo['index'];title,target,duration=self.demo['phases'][i]
        self.control.set_targets(target);self.sync(target);self.message.set('试运行%d/5：%s'%(i+1,title))
        if now-self.demo['phase_start']<duration:return
        self.demo_result['phase_endpoints'].append(dict(target_us=target,output_pwm_us=list(self.control.output)))
        passed=self.control.output==target
        if not passed or i==4:
            path=self.demo['path'];self.control.pause();self.demo_result.update(digital_checks_passed=passed,final=self.control.last_state)
            path.write_text(json.dumps(self.demo_result,indent=2),encoding='utf-8');self.demo=None
            self.message.set('试运行结束，中位保持。' if passed else '阶段未到目标，已暂停保持。');return
        self.demo['index']+=1;self.demo['phase_start']=now
    def poll(self):
        now=time.monotonic();dt=now-self.last;self.last=now
        if now-self.last_profile>1:self.refresh_mapping();self.last_profile=now
        self.demo_tick(now);self.control.tick(dt)
        self.readback.set('状态：'+{'idle':'未运行','running':'运行中','paused':'暂停保持','fault':'异常，需核对'}.get(self.control.mode,self.control.mode)+' | 实际PWM回读（μs）：'+(str(self.control.output) if self.control.last_state else '尚未连接'))
        if self.control.mode=='fault':self.demo=None;self.message.set('已停止更新；请托稳后点结束重新查询板卡状态。'+self.control.error)
        if now-self.last_status>.25:
            snapshot=self.snapshot();write_status(self.runtime_path,snapshot)
            if self.control.mode!='idle':write_status(ROOT/'build/neck_manual_active.json',snapshot)
            self.last_status=now
        self.window.after(50,self.poll)
    def close(self):
        if self.control.mode=='idle':
            if hasattr(self.control,'close'):self.control.close()
            self.window.destroy()
        else:self.pause();self.message.set('请先托稳并结束停PWM，再关闭窗口。')
def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--self-test',action='store_true');a=parser.parse_args()
    window=tk.Tk()
    if a.self_test:window.withdraw()
    panel=Panel(window)
    if a.self_test:
        window.update_idletasks();assert panel.control.mode=='idle' and panel.control.client is None
        assert panel.values()==panel.reference;assert [int(v.get()) for v in panel.scales]==[1500]*3
        assert window.winfo_reqheight()<=820 and window.winfo_reqwidth()<=960
        panel.control.close()
        window.destroy();print('NECK_V5_PANEL_SMOKE_PASS: idle, no client, no PWM')
    else:window.mainloop()
if __name__=='__main__':main()