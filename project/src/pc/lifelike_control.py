"""One NH sender for gaze and approved facial poses; no extra hardware loader."""
import copy,math,time
from head_control import HeadControl,CHANNELS,MASK
from head_session import HeadSession
from face_commission import FACE_CHANNELS
from nh22 import config,motion
from head_motion import MotionAxis,clamp
from lifelike_behavior import ExpressionEngine,pose_valid,jaw_probe_valid,jaw_observed_interval
from frontal_gaze import FrontalCoordinator
from jaw_motion import fixed_point_plan
from expression_presets import ALIASES,wink_signature
from action_library import CATALOG,HeadGesture,validate_actions,eye_gesture_settings,head_gesture_settings,head_up_room
class LifelikeControl(HeadControl):
    def __init__(self,profile,clock=time.monotonic,**kwargs):
        self.action_enabled=False;self.action_queue=[];self.active_action=None;self.action_last=None;self.action_requests={};self.action_history=[]
        self.clock=clock;self.life_config=copy.deepcopy(profile['lifelike']);self.engine=ExpressionEngine(self.life_config,clock());self.preview=None;self.last_preview=None
        self.previous_faces=0;self.last_head=None;self.last_send=clock();self.pose_map={p['channel']:p for p in self.life_config['poses']};super().__init__(profile,**kwargs)
        self.wink_trial=None;self.last_wink_trial=None
    def _eye_vertical_step(self):return 6  # 300us/s for explicit gestures; tracking still commands <=100us/s.
    def _neck_yaw_step(self):return 3  # 150us/s ceiling for gestures; tracking rates stay <=50/35us/s.
    def set_eye_gesture(self,delta,rate,ready=False):
        candidate=dict(eye_gesture_delta_us=delta,eye_gesture_rate_us_per_s=rate)
        settings=eye_gesture_settings(candidate)
        if not ready:raise ValueError('请勾选可现场观察动作方向和空间')
        if self.active_action or self.action_queue or self.preview:raise ValueError('请等当前动作结束再调整抬眼参数')
        self.profile.update(candidate)
        return settings
    def set_head_gesture_rates(self,yaw,pitch,ready=False):
        candidate=dict(head_gesture_yaw_rate_us_per_s=yaw,head_gesture_pitch_rate_us_per_s=pitch)
        settings=head_gesture_settings(candidate)
        if not ready:raise ValueError('请勾选可现场观察动作方向和空间')
        if self.active_action or self.action_queue or self.preview:raise ValueError('请等当前动作结束再调整头部动作速度')
        self.profile.update(candidate)
        return settings
    def _configure_extra_channels(self,state):
        self.action_enabled=False;self.action_queue=[];self.active_action=None
        self.wink_trial=None;self.last_wink_trial=None
        self.pose_map={p['channel']:copy.deepcopy(p) for p in self.life_config['poses']};self.engine=ExpressionEngine(self.life_config,self.clock());self.previous_faces=0;self.preview=None;self.last_preview=None
        for ch in FACE_CHANNELS:
            p=self.pose_map[ch];good=pose_valid(p) or jaw_probe_valid(p);n=p.get('neutral_us',1500)
            if type(n) is not int or not 600<=n<=2400:raise ValueError('Invalid facial candidate neutral')
            lo,hi=(p['min_us'],p['max_us']) if good else (n,n);rate=p['max_rate_us_per_s'] if good else 50
            jaw=self.life_config.get('jaw_setup')
            if ch==21 and jaw:
                n=jaw['closed_us'];rate=min(500,jaw.get('hardware_rate_us_per_s',50))
                if type(n) is not int or not 600<=n<=2400:raise ValueError('Invalid jaw candidate reference')
                if jaw.get('manual_full_range'):lo,hi=600,2400
                else:
                    lo,hi=jaw_observed_interval(jaw)
                    lo=min(lo,jaw.get('candidate_min_us',lo));hi=max(hi,jaw.get('candidate_max_us',hi))
            frame_step=max(1,min(100,math.ceil(rate/50)))
            if ch==21 and jaw and jaw.get('drive_mode')=='fixed_points':
                try:plan=fixed_point_plan(jaw)
                except ValueError:plan=None
                if plan:frame_step=plan['frame_step_us']
            seq=self.client.next_sequence();state=self.client.exchange(config(seq,ch,lo,hi,n,frame_step,False))
            if state['sequence']!=seq or state['active_mask']:raise RuntimeError('Lifelike idle configuration rejected')
        return state
    def extra_state(self):
        v=super().extra_state();v.update(controller_build='lifelike_v6_3',jaw_drive_mode=self.life_config.get('jaw_setup',{}).get('drive_mode','continuous'),neck_tracking_rate_us_per_s=self.profile.get('neck_tracking_rate_us_per_s',[20,15]),neck_tracking_gain=self.profile.get('neck_tracking_gain',.35),expression_style=self.life_config.get('expression_style','classic'),life_state=self.engine.state,life_ready_channels=sorted(self.engine.poses),life_blocked=copy.deepcopy(self.engine.blocked),speech=dict(kind=self.engine.speech.kind,name=self.engine.speech.name,energy=self.engine.energy),blink_ratio=self.engine.blink_ratio,life_preview=copy.deepcopy(self.preview),life_last_preview=copy.deepcopy(self.last_preview),frontal_preferred=self.profile.get('prefer_frontal',True));v.update(expression_preset=self.engine.preset.name,wink_ratio=self.engine.wink_ratio,wink_trial=copy.deepcopy(self.wink_trial),last_wink_trial=copy.deepcopy(self.last_wink_trial));v.update(action_library_enabled=self.action_enabled,action_active=self._action_snapshot(),action_pending=[r['name'] for r in self.action_queue],action_last=copy.deepcopy(self.action_last),action_history=copy.deepcopy(self.action_history));v['eye_gesture']=eye_gesture_settings(self.profile);v['head_gesture']=head_gesture_settings(self.profile);v['head_up_room_us']=head_up_room(self.output,self.profile);v['tracking_headroom_reserved_us']=80 if self.action_enabled and self._tracking_headroom() else 0;return v
    def _action_snapshot(self):
        row=self.active_action or {}
        result={k:copy.deepcopy(v) for k,v in row.items() if k!='gesture'}
        if row.get('gesture'):result['progress']=row['gesture'].progress(self.clock())
        elif row.get('waiting_headroom'):
            result['progress']=dict(phase='追踪中分配抬头余量',remaining_s=round(max(0,row['headroom_deadline']-self.clock()),1),
                available_us=head_up_room(self.output,self.profile),required_us=80)
        return result
    def _frontal_coordinator(self,values):
        return FrontalCoordinator(dict(self.profile,head_up_reserve_us=80 if self.action_enabled else 0),values)
    def _tracking_headroom(self):return self.tracking=='coordinated' and isinstance(self.coordinator,FrontalCoordinator)
    def set_follow(self,kind):
        if self.active_action or self.action_queue:
            if kind!='manual':raise ValueError('动作执行中；可先取消动作，再切换跟随模式')
            self._abort_actions('manual_override')
        if self.preview:raise ValueError('Wait for the single-joint preview to finish')
        super().set_follow(kind)
        if kind=='coordinated' and self.motion_style=='natural' and self.profile.get('prefer_frontal',True):self.coordinator=self._frontal_coordinator(self.output)
    def _visual_tick(self):
        # Expression scheduling never skips camera freshness checks or valid targets.
        # The existing coordinator already holds briefly when no face is visible.
        result=super()._visual_tick()
        if self.active_action and (self.active_action.get('gesture') or self.active_action.get('waiting_headroom')) and self.active_action['tracking']!='manual' and self.tracking=='manual':
            self._abort_actions('visual_hold')
        return result
    def begin_identification(self):
        if self.active_action or self.action_queue:raise ValueError('先取消动作库动作，再辨识颈部方向')
        if self.engine.state!='off' or self.preview:raise ValueError('Stop expressions before neck identification')
        return super().begin_identification()
    def enable_life(self,ready=False):
        if self.mode!='running':raise ValueError('请先在本窗口开始控制')
        if self.preview:raise ValueError('请等待当前单路预览完成')
        if self.engine.poses and not ready:raise ValueError('请勾选已确认面部接线和动作点')
        self.engine.enable(self.clock());self.note='Frontal gaze and lifelike expression scheduling enabled'
    def set_blink_policy(self,pair_verified=False,camera_clear=False):
        if type(pair_verified) is not bool or type(camera_clear) is not bool:raise ValueError('需要明确的现场观察确认')
        if pair_verified and not {6,8}.issubset(self.engine.poses):raise ValueError('双眼眨眼不可用：上眼帘未批准或已因遮挡摄像头屏蔽；请使用右眼wink')
        if camera_clear and not pair_verified:raise ValueError('先确认两眼同闭同睁')
        self.life_config.update(blink_pair_verified=pair_verified,camera_clear_blink_verified=camera_clear,automatic_blink=pair_verified)
        self.engine.config.update(blink_pair_verified=pair_verified,camera_clear_blink_verified=camera_clear,automatic_blink=pair_verified)
        if not pair_verified:self.engine.blink=None
        return copy.deepcopy(self.life_config)
    def trial_tracking_blink(self,ready=False):
        if not ready or self.engine.state not in ('warming','active'):raise ValueError('先确认可观察并开启表情')
        self.engine.tracking_active=self.tracking in ('eyes','coordinated')
        if not self.engine.blink_once(self.clock(),clearance_trial=True,direction_trial=True):raise ValueError('先预览并批准两侧上眼帘，并等待上次眨眼完成')
    def set_expression_style(self,style):
        if style not in ('soft','lively','active'):raise ValueError('Unknown expression style')
        self.life_config['expression_style']=style;self.engine.config['expression_style']=style
        return copy.deepcopy(self.life_config)
    def trial_right_wink(self,ready=False):
        if not ready or self.mode!='running' or self.preview:raise ValueError('先开始会话、开启表情，并勾选可现场观察右眼及摄像头画面')
        self.engine.wink_once(self.clock(),trial=True)
        event=self.engine.wink.event
        self.wink_trial=dict(pose=wink_signature(self.pose_map[8]),frames=0,max_delta_us=0,status='running',expected_end=event[0]+sum(event[1:4]))
        self.last_wink_trial=None
    def approve_right_wink(self,confirmed=False):
        t=self.last_wink_trial
        if not confirmed or self.wink_trial or not t or t['status']!='completed' or not t['frames'] or not t['max_delta_us']:
            raise ValueError('先完成右眼 wink 试动作，再勾选已观察闭合、回张且摄像头画面无遮挡')
        if t['pose']!=wink_signature(self.pose_map[8]):raise ValueError('眼帘点位已改变，需要重新试动作')
        self.life_config['wink_right_approval']=dict(verified=True,tracking_clear=True,pose=t['pose'],operator_confirmed_epoch=time.time())
        self.engine.config['wink_right_approval']=copy.deepcopy(self.life_config['wink_right_approval'])
        return copy.deepcopy(self.life_config)
    def set_neck_tracking_speed(self,style):
        if style not in ('normal','faster'):raise ValueError('Unknown neck speed mode')
        rates,gain=([20,15],.35) if style=='normal' else ([40,30],.65)
        self.profile.update(neck_tracking_rate_us_per_s=rates,neck_tracking_gain=gain)
        self.motion_bank.neck_rates=list(rates)
        if isinstance(self.coordinator,FrontalCoordinator):self.coordinator.rate_caps=list(rates);self.coordinator.gain=gain
        self.life_config.update(neck_tracking_mode=style,neck_tracking_rate_us_per_s=rates,neck_tracking_gain=gain,neck_speed_physical_verified=False)
        return copy.deepcopy(self.life_config)
    def demo_expressions(self):
        if self.engine.state not in ('warming','active'):raise ValueError('先开启活人感，再点无声表情演示')
        if self.engine.speech.kind is not None:raise ValueError('先停止正在播放的语音，再做无声演示')
        frames=[]
        for i in range(400):
            t=i*.02;phase=t%1.1
            frames.append((.85*math.sin(math.pi*(phase-.15)/.6)**2) if .15<phase<.75 else 0.)
        self.speech_timeline(frames,.02,'8秒无声表情演示')
        self.engine.mood='engaged';self.engine.mood_end=self.clock()+8
        self.engine.blink_once(self.clock())
    def disable_life(self,immediate=False):self.engine.stop(self.clock(),immediate);self.note='Expressions returning to neutral' if not immediate else 'Facial PWM disabled'
    def preview_joint(self,ch,ready=False):
        if self.active_action or self.action_queue:raise ValueError('先取消动作库动作，再做单路预览')
        if self.mode!='running':raise ValueError('请先在本窗口开始控制')
        if not ready:raise ValueError('请勾选当前选中通道接线/范围已确认并可观察')
        if self.engine.state!='off' or self.preview:raise ValueError('请先停表情并等待预览完成')
        p=self.pose_map.get(ch)
        if p is None or not pose_valid(p):raise ValueError('Complete the selected candidate and confirmed range first')
        n=p['neutral_us'];rate=min(400,p['max_rate_us_per_s']);duration=abs(p['action_us']-n)/rate+1.
        self.preview=dict(channel=ch,started=self.clock(),half_s=duration,neutral_us=n,target_us=p['action_us'],rate_us_per_s=rate,status='running',frames=0)
        self.preview_axis=MotionAxis(n,p['min_us'],p['max_us']);self.last_send=self.clock()
    def probe_jaw(self,direction,ready=False):
        if self.life_config.get('jaw_setup'):raise ValueError('下颚已确认单方向张嘴，请使用“继续张开25μs”')
        if self.mode!='running' or not ready:raise ValueError('先开始本窗口控制，选下颚并确认本路接线')
        if self.engine.state!='off' or self.preview:raise ValueError('先停表情，等待当前预览结束')
        p=self.pose_map[21]
        if not jaw_probe_valid(p) or direction not in (-1,1):raise ValueError('下颚小步探查配置无效')
        n=p['neutral_us'];rate=p['max_rate_us_per_s']
        self.preview=dict(channel=21,started=self.clock(),half_s=25/rate+1,neutral_us=n,target_us=n+25*direction,rate_us_per_s=rate,status='running',frames=0,kind='jaw_probe')
        self.preview_axis=MotionAxis(n,p['min_us'],p['max_us']);self.last_send=self.clock()
    def probe_jaw_open(self,ready=False):
        if self.mode!='running' or not ready:raise ValueError('请先开始控制并确认本路接线及现场观察')
        if self.engine.state!='off' or self.preview:raise ValueError('先停表情，等待当前探查完成；眼颈追踪不用停')
        j=self.life_config.get('jaw_setup')
        jaw_observed_interval(j)
        n=j['closed_us'];known=j['observed_open_us'];step=min(25,j['max_step_us']);direction=1 if known>n else -1
        target=min(j.get('candidate_max_us',2400),known+step) if direction>0 else max(j.get('candidate_min_us',600),known-step)
        if target==known:raise ValueError('已到本次候选边界，先使用已确认范围')
        rate=min(50,j['probe_rate_us_per_s'])
        self.preview=dict(channel=21,started=self.clock(),half_s=abs(n-target)/rate+1,neutral_us=n,target_us=target,rate_us_per_s=rate,status='running',frames=0,kind='jaw_open_calibration')
        self.preview_axis=MotionAxis(n,min(n,target),max(n,target));self.last_send=self.clock()
    def preview_jaw_manual(self,target,ready=False):
        if self.mode!='running' or not ready:raise ValueError('先开始本窗口控制并确认当前下颚可观察')
        if self.engine.state!='off' or self.preview:raise ValueError('先停表情，等待当前预览完成；眼颈追踪不用停')
        j=self.life_config.get('jaw_setup')
        if not j or not j.get('manual_full_range'):raise ValueError('需重新开始使用手动范围已开放的会话')
        if type(target) is not int or not 600<=target<=2400:raise ValueError('请输入设备支持的600–2400μs脉宽')
        n=j['closed_us'];rate=min(50,j['probe_rate_us_per_s'])
        self.preview=dict(channel=21,started=self.clock(),half_s=abs(n-target)/rate+1,neutral_us=n,target_us=target,rate_us_per_s=rate,status='running',frames=0,kind='jaw_manual')
        self.preview_axis=MotionAxis(n,600,2400);self.last_send=self.clock()
    def record_jaw_open(self):
        t=self.last_preview;j=self.life_config.get('jaw_setup')
        if self.preview or self.engine.state!='off' or not j or not t or t.get('kind') not in ('jaw_open_calibration','jaw_manual') or t.get('status')!='completed' or not t.get('frames'):raise ValueError('先完成下颚预览并观察顺畅回闭嘴')
        value=t['target_us']
        if t['kind']=='jaw_manual':
            if not 600<=value<=2400 or value==j['closed_us']:raise ValueError('张嘴点应与已记录闭嘴点不同')
            j['candidate_min_us']=min(j.get('candidate_min_us',value),value,j['closed_us'])
            j['candidate_max_us']=max(j.get('candidate_max_us',value),value,j['closed_us'])
        else:
            known=j['observed_open_us'];direction=1 if known>j['closed_us'] else -1
            if not 0<(value-known)*direction<=25:raise ValueError('不能跨步批准下颚行程')
        j['observed_open_us']=value;j['operator_open_observed']=True;j['automatic_committed']=False;j['last_operator_observed_epoch']=time.time()
        if j.get('drive_mode')=='fixed_points':
            try:fixed_point_plan(j)
            except ValueError:j['fixed_point_verified']=False
        self.engine=ExpressionEngine(self.life_config,self.clock())
        return copy.deepcopy(self.life_config)
    def use_jaw_for_speech(self,ready=False):
        if not ready or self.engine.state!='off' or self.preview:raise ValueError('先停表情并确认已观察的张嘴点顺畅')
        j=self.life_config.get('jaw_setup')
        lo,hi=jaw_observed_interval(j)
        plan=fixed_point_plan(j)
        rate=plan['frame_step_us']*50 if plan else 300
        p=copy.deepcopy(self.pose_map[21]);p.update(neutral_us=j['closed_us'],min_us=lo,max_us=hi,action_us=j['observed_open_us'],max_rate_us_per_s=rate,probe_only=False,range_confirmed=True,action_verified=True,enabled=True)
        if not pose_valid(p):raise ValueError('自动开合区间包含已记录卡滞点，不能启用')
        self.pose_map[21]=p
        j['automatic_committed']=True
        self.life_config['poses']=[copy.deepcopy(self.pose_map[p['channel']]) for p in self.life_config['poses']]
        self.engine=ExpressionEngine(self.life_config,self.clock());return copy.deepcopy(self.life_config)
    def approve_pose(self,ch):
        t=self.last_preview
        if self.pose_map[ch].get('automatic_inhibited') is True:raise ValueError('该通道因干扰视觉已屏蔽自动输出；手动预览不解除屏蔽')
        if self.engine.state!='off' or self.preview:raise ValueError('先完成预览并停表情，再记录观察')
        if not t or t['channel']!=ch or t['status']!='completed':raise ValueError('请先预览选中通道，观察中位和动作方向')
        if t.get('kind') in ('jaw_probe','jaw_open_calibration','jaw_manual'):raise ValueError('请用下颚专用记录和说话按钮，保存已观察的闭嘴/张嘴区间')
        self.pose_map[ch].update(action_verified=True,enabled=True);self.life_config['poses']=[copy.deepcopy(self.pose_map[p['channel']]) for p in self.life_config['poses']]
        self.engine=ExpressionEngine(self.life_config,self.clock());return copy.deepcopy(self.life_config)
    def update_pose(self,pose):
        ch=pose.get('channel');old=self.pose_map.get(ch)
        if old is None or not pose_valid(pose):raise ValueError('请检查动作点、范围和速度上限')
        if self.engine.state!='off' or self.preview:raise ValueError('Stop expressions/preview before editing')
        if self.mode!='idle' and (any(pose[k]!=old[k] for k in ('neutral_us','min_us','max_us')) or pose['max_rate_us_per_s']>old['max_rate_us_per_s']):raise ValueError('修改中位/范围或提高速度，需要先托稳结束控制，再保存并重新开始')
        pose=copy.deepcopy(pose);pose.update(action_verified=False,enabled=False);self.pose_map[ch]=pose
        if old.get('automatic_inhibited') is True:
            pose.update(automatic_inhibited=True,automatic_inhibited_reason=old.get('automatic_inhibited_reason','该通道自动输出已屏蔽'))
        self.life_config['poses']=[copy.deepcopy(self.pose_map[p['channel']]) for p in self.life_config['poses']];self.engine=ExpressionEngine(self.life_config,self.clock());return copy.deepcopy(self.life_config)
    def speech_timeline(self,frames,step,name='audio'):
        if self.engine.state not in ('warming','active'):raise ValueError('请先开启活人感，再播放语音')
        return self.engine.speech.timeline(frames,step,self.clock(),name)
    def life_event(self,event):
        kind=event.get('type')
        if kind=='action':return self.submit_actions(event)
        if kind=='action.cancel':return self.cancel_actions(event.get('request_id'))
        if kind=='stop':self.disable_life();return
        if kind=='speech.end':self.engine.speech.stop(event.get('token'));return
        if self.engine.state not in ('warming','active'):raise ValueError('Lifelike mode is not enabled')
        if kind=='speech.energy':
            self.engine.speech.sample(self.clock())
            if self.engine.speech.kind=='timeline':raise ValueError('Local audio playback has priority; stop it before TTS')
            self.engine.speech.external(event.get('energy'),self.clock(),event.get('id','tts'))
        elif kind=='blink':
            missing=[self.pose_map[ch]['label'] for ch in (6,8) if ch not in self.engine.poses]
            if missing:raise ValueError('双眼眨眼未执行：'+ '、'.join(missing)+'未批准或已自动屏蔽；请使用右眼wink')
            if not self.engine.blink_once(self.clock()):raise ValueError('眨眼未执行：请确认两眼方向和追踪视野，或等待上次眨眼完成')
        elif kind=='expression':
            name=ALIASES.get(event.get('name'),event.get('name'))
            if name=='wink':
                self.engine.wink_once(self.clock(),event.get('intensity',.8));return
            if name in ('neutral','smile','sad'):
                self.engine.preset.trigger(name,self.clock(),event.get('duration_s',3),event.get('intensity',.8),self.engine.poses)
                self.engine.mood='neutral';self.engine.mood_end=0.
                if name=='neutral':self.engine.wink.event=None
                return
            if name not in ('engaged','curious'):raise ValueError('Unknown expression')
            duration=event.get('duration_s',2)
            if not isinstance(duration,(int,float)) or not math.isfinite(duration) or not .1<=duration<=20:raise ValueError('Invalid expression duration')
            self.engine.mood=event['name'];self.engine.mood_end=self.clock()+duration
        else:raise ValueError('Unsupported intent; raw PWM is not accepted')
    def pause(self):
        self._abort_actions('paused');self.action_enabled=False
        self.preview=None;self.engine.stop(self.clock(),True);super().pause()
    def end(self,head_supported=False):
        if self.mode!='idle' and not head_supported:raise ValueError('Support head before disabling PWM')
        self._abort_actions('ended');self.action_enabled=False
        self.preview=None;self.engine.stop(self.clock(),True);return super().end(head_supported)
    def _send_motion(self,values):
        now=self.clock();dt=clamp(now-self.last_send,0,.1);self.last_send=now
        if self.active_action and self.active_action.get('gesture'):
            values=list(values)
            for i,u in self.active_action['gesture'].sample(now).items():values[i]=u;self.command[i]=float(u)
        activity=0 if self.last_head is None or not dt else max(abs(a-b)/dt/rate for a,b,rate in zip(values,self.last_head,[200,100,20,15,15]));self.last_head=list(values)
        self.engine.tracking_active=self.tracking in ('eyes','coordinated')
        poses=self.engine.step(now,activity)
        if self.wink_trial:
            t=self.wink_trial
            if self.engine.wink.event is not None and 8 in poses:
                t['frames']+=1;t['max_delta_us']=max(t['max_delta_us'],abs(poses[8]-t['pose']['neutral_us']))
            else:
                self.last_wink_trial=dict(t,status='completed' if self.engine.state=='active' and now>=t['expected_end'] and t['frames'] else 'aborted');self.wink_trial=None
        if not self.preview:
            poses={ch:u for ch,u in poses.items() if self.pose_map[ch].get('automatic_inhibited') is not True}
        if self.preview:
            t=self.preview;elapsed=now-t['started'];target=t['target_us'] if elapsed<t['half_s'] else t['neutral_us']
            if elapsed>=2*t['half_s'] and abs(self.preview_axis.position-t['neutral_us'])<1:
                self.last_preview=dict(t,status='completed' if t['frames'] else 'not_sent',completed=now);self.preview=None
            else:poses={t['channel']:round(self.preview_axis.step(target,dt,t.get('rate_us_per_s',100),t.get('rate_us_per_s',100)*5,t.get('rate_us_per_s',100)*40))};t['frames']+=1
        pulses=[0]*22
        for ch,u in zip(CHANNELS,values):pulses[ch]=u
        mask=MASK
        for ch,u in poses.items():
            p=self.pose_map[ch]
            limits=(p['min_us'],p['max_us'])
            if ch==21 and self.preview and self.preview.get('kind')=='jaw_open_calibration':limits=(min(self.preview['neutral_us'],self.preview['target_us']),max(self.preview['neutral_us'],self.preview['target_us']))
            if ch==21 and self.preview and self.preview.get('kind')=='jaw_manual':limits=(600,2400)
            if not limits[0]<=u<=limits[1]:raise ValueError('Expression outside confirmed bounds')
            pulses[ch]=u;mask|=1<<ch
        seq=self.client.next_sequence();state=self.client.exchange(motion(seq,mask,pulses));allowed=mask|self.previous_faces
        if state['sequence']!=seq or state['status']&~5 or state['active_mask']&~allowed:raise RuntimeError('Lifelike acknowledgement invalid')
        if self.active_action and self.active_action.get('gesture'):
            actual=[state['output_us'][ch] for ch in CHANNELS]
            self.active_action['gesture'].observe(now,values,actual)
        self.previous_faces=(state['active_mask']|mask)&sum(1<<ch for ch in FACE_CHANNELS);return state
    def set_action_library(self,enabled,ready=False):
        if type(enabled) is not bool:raise ValueError('动作库开关无效')
        if enabled and (self.mode!='running' or not ready or self.preview or self.tracking=='identify'):
            raise ValueError('先开始本窗口会话，确认动作空间、方向与现场观察，再开启动作库')
        if not enabled:self.cancel_actions()
        self.action_enabled=enabled
        if isinstance(self.coordinator,FrontalCoordinator):self.coordinator.set_headroom(80 if enabled else 0)
        return enabled
    def _validate_action(self,name):
        if CATALOG[name]['kind']=='head':
            if not self.profile.get('neck_position_control_operator_confirmed'):raise ValueError('颈部位置舵机未确认')
            baseline=list(self.output)
            if name=='head_up' and self._tracking_headroom() and head_up_room(baseline,self.profile)<78:
                # The queued request waits for reserved tracking room; validation
                # here checks only the pose's hard range and known directions.
                if any(abs(a-b)>100 for a,b in zip(baseline[2:],self.reference[2:])):raise ValueError('颈部已超出现有自动范围')
                baseline[3:5]=self.reference[3:5]
            HeadGesture(name,baseline,self.profile,self.clock())
        else:
            if self.engine.state not in ('warming','active'):raise ValueError('先开启表情，才可执行微笑、难过或wink')
            if name=='wink':
                p=self.engine.poses.get(8);approval=self.engine.config.get('wink_right_approval',{})
                if self.engine.state!='active' or not p or approval.get('verified') is not True or approval.get('tracking_clear') is not True or approval.get('pose')!=wink_signature(p):
                    raise ValueError('右眼wink方向与摄像头画面无遮挡尚未完成确认')
                if self.engine.blink is not None or self.engine.wink.event is not None:raise ValueError('等待上次眨眼完成')
            elif not {2,4}.issubset(self.engine.poses):raise ValueError('先确认两侧眉部动作方向')
    def submit_actions(self,event):
        if set(event)-{'type','request_id','actions'}:raise ValueError('动作库仅接收登记ID，不能传PWM、角度或自定义参数')
        names=validate_actions(event.get('actions'))
        request=event.get('request_id')
        if type(request) is not str or not 1<=len(request)<=80:raise ValueError('需要有效动作请求ID')
        if not self.action_enabled or self.mode!='running':raise ValueError('动作库未开启；大模型不能自行开启控制')
        if request in self.action_requests:return dict(self.action_requests[request],duplicate=True)
        if self.active_action or self.action_queue or self.preview or self.tracking=='identify':raise ValueError('当前动作或调试尚未完成，请稍候再试')
        if not names:raise ValueError('空动作列表无需提交')
        for name in names:self._validate_action(name)
        result=dict(request_id=request,accepted=True,actions=names)
        self.action_requests[request]=dict(result)
        if len(self.action_requests)>64:del self.action_requests[next(iter(self.action_requests))]
        self.action_queue=[dict(name=n,request_id=request) for n in names]
        self.action_last=dict(request_id=request,status='queued',actions=names)
        return result
    def _abort_actions(self,reason):
        if self.active_action or self.action_queue:
            row=self.active_action or self.action_queue[0]
            self.action_last=dict(request_id=row['request_id'],name=row['name'],status='aborted',reason=reason)
            if row.get('gesture'):self.action_last['pwm_evidence']=row['gesture'].progress(self.clock())
            self.action_history=(self.action_history+[copy.deepcopy(self.action_last)])[-16:]
        self.active_action=None;self.action_queue=[]
    def cancel_actions(self,request_id=None):
        current=self.active_action or (self.action_queue[0] if self.action_queue else None)
        if not current or (request_id is not None and request_id!=current['request_id']):return False
        self.action_queue=[]
        if self.active_action and self.active_action.get('gesture'):
            self.active_action['gesture'].cancel(self.clock(),list(self.output));self.active_action['cancelled']=True
        else:
            if self.active_action and self.engine.state in ('warming','active'):
                self.engine.preset.trigger('neutral',self.clock(),.6,.8,self.engine.poses)
            if not self.active_action:self.action_last=dict(request_id=current['request_id'],name=current['name'],status='cancelled')
            self._abort_actions('cancelled')
        return True
    def _finish_action(self,status='completed',reason=''):
        row=self.active_action
        if not row:return
        self.active_action=None
        self.action_last=dict(request_id=row['request_id'],name=row['name'],status=status,reason=reason)
        if row.get('gesture'):
            self.action_last['pwm_evidence']=row['gesture'].progress(self.clock())
            self.action_last['result_label']='PWM路径及回位已确认；实物运动待观察' if status=='completed' else reason or status
        self.action_history=(self.action_history+[copy.deepcopy(self.action_last)])[-16:]
        if row.get('gesture'):
            self.command=list(map(float,self.output));self.desired=list(self.output);self.motion_bank.reset(self.output)
            if self.tracking in ('eyes','coordinated'):
                try:
                    HeadControl.set_follow(self,self.tracking)
                    if self.tracking=='coordinated' and self.motion_style=='natural' and self.profile.get('prefer_frontal',True):self.coordinator=self._frontal_coordinator(self.output)
                except Exception as exc:
                    self.tracking='manual';self.note='动作回位后保持：'+str(exc)
        if status!='completed':self.action_queue=[]
    def _action_tick(self,now):
        row=self.active_action
        if row:
            gesture=row.get('gesture')
            if row.get('waiting_headroom'):
                if not self._tracking_headroom():self._finish_action('aborted','追踪已停止，取消等待抬头余量')
                elif now>row['headroom_deadline']:self._finish_action('rejected','追踪未分配足够抬头余量，请检查画面和参考姿态')
                elif head_up_room(self.output,self.profile)>=78:
                    row.pop('waiting_headroom');row['gesture']=HeadGesture('head_up',list(self.output),self.profile,now)
            elif gesture:
                if now>=gesture.end and gesture.returned(self.output):
                    error='' if row.get('cancelled') else gesture.completion_error()
                    if error:self._finish_action('aborted',error);self.pause()
                    else:self._finish_action('cancelled' if row.get('cancelled') else 'completed')
                elif now>gesture.end+3:self._finish_action('aborted','PWM回参考未确认');self.pause()
            elif self.engine.state not in ('warming','active'):
                self._finish_action('aborted','表情已停')
            elif now>=row['ends_at']:self._finish_action()
        if not self.active_action and self.action_queue:
            row=self.action_queue.pop(0);name=row['name']
            self.active_action=dict(row,started=now,tracking=self.tracking)
            try:
                self._validate_action(name)
                if CATALOG[name]['kind']=='head':
                    if name=='head_up' and self._tracking_headroom() and head_up_room(self.output,self.profile)<78:
                        self.active_action.update(waiting_headroom=True,headroom_deadline=now+10.)
                    else:self.active_action['gesture']=HeadGesture(name,list(self.output),self.profile,now)
                else:
                    self.life_event(dict(type='expression',name=name,duration_s=3,intensity=.8))
                    self.active_action['ends_at']=now+3 if name!='wink' else now+sum(self.engine.wink.event[1:4])+.1
            except Exception as exc:self._finish_action('rejected',str(exc))
    def tick(self,dt):
        if self.mode=='running':self._action_tick(self.clock())
        super().tick(dt)
        if self.mode=='fault':self._abort_actions('control_fault');self.action_enabled=False
class LifelikeSession(HeadSession):
    def __init__(self,profile,**kwargs):super().__init__(profile,core_class=LifelikeControl,**kwargs)
    def enable_life(self,ready=False):return self._invoke('enable_life',ready)
    def set_blink_policy(self,pair_verified=False,camera_clear=False):return self._invoke('set_blink_policy',pair_verified,camera_clear)
    def trial_tracking_blink(self,ready=False):return self._invoke('trial_tracking_blink',ready)
    def set_expression_style(self,style):return self._invoke('set_expression_style',style)
    def set_action_library(self,enabled,ready=False):return self._invoke('set_action_library',enabled,ready)
    def set_eye_gesture(self,delta,rate,ready=False):
        result=self._invoke('set_eye_gesture',delta,rate,ready)
        profile=self.profile;profile.update(eye_gesture_delta_us=delta,eye_gesture_rate_us_per_s=rate);self.profile=profile
        return result
    def set_head_gesture_rates(self,yaw,pitch,ready=False):
        result=self._invoke('set_head_gesture_rates',yaw,pitch,ready)
        profile=self.profile;profile.update(head_gesture_yaw_rate_us_per_s=yaw,head_gesture_pitch_rate_us_per_s=pitch);self.profile=profile
        return result
    def trial_right_wink(self,ready=False):return self._invoke('trial_right_wink',ready)
    def approve_right_wink(self,confirmed=False):return self._invoke('approve_right_wink',confirmed)
    def set_neck_tracking_speed(self,style):return self._invoke('set_neck_tracking_speed',style)
    def demo_expressions(self):return self._invoke('demo_expressions')
    def disable_life(self,immediate=False):return self._invoke('disable_life',immediate)
    def preview_joint(self,ch,ready=False):return self._invoke('preview_joint',ch,ready)
    def probe_jaw(self,direction,ready=False):return self._invoke('probe_jaw',direction,ready)
    def probe_jaw_open(self,ready=False):return self._invoke('probe_jaw_open',ready)
    def preview_jaw_manual(self,target,ready=False):return self._invoke('preview_jaw_manual',target,ready)
    def record_jaw_open(self):return self._invoke('record_jaw_open')
    def use_jaw_for_speech(self,ready=False):return self._invoke('use_jaw_for_speech',ready)
    def approve_pose(self,ch):return self._invoke('approve_pose',ch)
    def update_pose(self,pose):return self._invoke('update_pose',pose)
    def speech_timeline(self,frames,step,name='audio'):return self._invoke('speech_timeline',frames,step,name)
    def life_event(self,event):return self._invoke('life_event',event)
