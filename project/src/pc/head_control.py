"""One owner sends both eyes and the three supported neck outputs together."""
import copy,time
from nh22 import config,motion,query,stop
from neck_control import NeckControl
from head_transport import HeadClient
from neck_yaw_midpoint import ROOT,GUARD,GUARD_HASH,ALLOWED_IDLE_CONFIG,acquire_run_lock
from neck_presets import neck_neutral,rod_up_signs
from loaded_visual_trial import visual_pulse
from head_coordination import Coordinator,identification_plan,analyze_identification,validate_direction_record
from head_motion import MotionBank,NaturalCoordinator
CHANNELS=(0,1,18,19,20);MASK=3|(7<<18)
class HeadControl(NeckControl):
    channels=CHANNELS
    def __init__(self,profile,vision=None,client_factory=HeadClient,lock_factory=acquire_run_lock,validate_guard_each_tick=True):
        super().__init__(profile,client_factory,lock_factory,validate_guard_each_tick)
        self.reference=[1500,1500]+neck_neutral(profile);self.desired=list(self.reference);self.output=list(self.reference)
        self.command=[float(u) for u in self.reference];self.hold_pose=list(self.reference)
        self.vision=vision or (lambda:None);self.tracking='manual';self.coordinator=None;self.camera_session=None
        self.calibration=None;self.ident=None;self.ident_result=None;self.note='Manual five-axis mode; not started'
        self.last_good_record=copy.deepcopy(profile.get('saved_direction_record'))
        self.motion_style=profile.get('motion_style','legacy');self.motion_bank=MotionBank(self.output,profile.get('eye_vertical_limits_us',[1000,2000]),neck_neutral(profile),profile.get('neck_tracking_rate_us_per_s'))
        self.motion_frames=0;self.motion_start=None
    def validate_targets(self,values):
        limits=[(1100,1900),tuple(self.profile.get('eye_vertical_limits_us',[1000,2000]))]+[(1100,1900)]*3
        if len(values)!=5 or any(type(v) is not int or not lo<=v<=hi for v,(lo,hi) in zip(values,limits)):
            raise ValueError('Five actual PWM targets required within the displayed envelopes')
    def set_targets(self,values):
        self.validate_targets(values);self.desired=list(values)
    def _eye_vertical_step(self):return 2
    def _neck_yaw_step(self):return 2
    def extra_state(self):
        return dict(tracking=self.tracking,note=self.note,motion_style=self.motion_style,motion_frames=self.motion_frames,board_counters={k:(self.last_state or {}).get(k) for k in ('accepted','invalid','stale','watchdog_events')},transport_recoveries=dict(query=getattr(self.client,'query_recoveries',0),motion_retry=getattr(self.client,'confirmed_motion_retries',0)),last_good_direction=copy.deepcopy(self.last_good_record),calibration=copy.deepcopy(self.calibration),
                    identification_phase=None if self.ident is None else self.ident['phases'][self.ident['index']]['name'],
                    identification_result=copy.deepcopy(self.ident_result))
    def start(self):
        if self.mode in ('running','paused'):return super().start()
        if self.mode!='idle':raise RuntimeError('End the previous fault session first')
        if not self.profile.get('operator_ready_this_session'):raise ValueError('Confirm five signal connections, external supply and supported head in this window')
        if self.profile.get('camera_mount')!='moves_with_eyeball':raise ValueError('Eye-mounted camera confirmation required')
        if not (self.profile.get('yaw_reference_operator_verified') and self.profile.get('pair_first_output_no_abnormal_operator_confirmed')):
            raise ValueError('Observed neck reference is required')
        from eye_follow_panel import verified_command
        verified_command('both',self.profile.get('vertical_reverse',False),False)
        self._guard();self.lock=self.lock_factory(ROOT/'build/eye_feedback.lock')
        try:
            self.client=self.client_factory(bind='192.168.10.10',timeout=.1)
            state=self.client.exchange(query())
            if state['status'] or state['active_mask'] or state['configured_mask']&~((1<<22)-1):
                raise RuntimeError('Another controller or latched session owns the board; no actuator writes sent')
            vlo,vhi=self.profile.get('eye_vertical_limits_us',[1000,2000])
            limits=[(1100,1900),(vlo,vhi)]+[(1100,1900)]*3
            self.reference=[1500,1500]+neck_neutral(self.profile)
            for ch,(lo,hi),neutral in zip(CHANNELS,limits,self.reference):
                step=self._eye_vertical_step() if ch==1 else self._neck_yaw_step() if ch==18 else 4 if ch==0 else 2
                seq=self.client.next_sequence();state=self.client.exchange(config(seq,ch,lo,hi,neutral,step,ch>=18))
                if state['sequence']!=seq or state['active_mask']:raise RuntimeError('Idle five-channel configuration rejected')
            state=self._configure_extra_channels(state)
        except BaseException:self._release();raise
        self.command=[float(u) for u in self.reference];self.desired=list(self.reference);self.output=list(self.reference);self.hold_pose=list(self.reference)
        self.mode='running';self.error='';self.last_state=state;self.tracking='manual';self.note='Five-axis manual mode'
        self.motion_bank.reset(self.output);self.motion_frames=0;self.motion_start=time.monotonic()
    def _fresh_vision(self):
        row=self.vision()
        if row is None:raise ValueError('No fresh USB Cam frame')
        sid=row.get('vision',{}).get('source_session_id')
        if not sid:raise ValueError('Camera session missing')
        visual_pulse(row,time.monotonic(),self.camera_session or sid)
        return row
    def set_follow(self,kind):
        if kind not in ('eyes','coordinated','manual'):raise ValueError('Unknown tracking mode')
        if self.mode not in ('running','paused'):raise RuntimeError('Start the five-axis session first')
        if kind=='manual':
            self.tracking='manual';self.ident=None;self.set_targets(list(self.output));self.command=list(map(float,self.output));self.motion_bank.reset(self.output);return
        if kind=='coordinated' and not self.profile.get('neck_position_control_operator_confirmed'):
            raise ValueError('Position-controlled neck servo confirmation required')
        self.camera_session=None
        row=self._fresh_vision()
        if row['vision']['target'] is None:raise ValueError('Place a face inside the USB Cam view first')
        expected_size=self.profile.get('camera_frame_size')
        if expected_size and [row['vision'].get('width'),row['vision'].get('height')]!=expected_size:raise ValueError('相机画面尺寸变化，请核对采集配置')
        self.camera_session=row['vision']['source_session_id'];self.ident=None
        if kind=='coordinated':
            self.calibration=validate_direction_record(self.last_good_record,self.profile,self.camera_session)
            n=neck_neutral(self.profile);signs=rod_up_signs(self.profile)
            if any(abs(a-b)>100 for a,b in zip(self.output[2:],n)):raise ValueError('Return neck inside the 100us envelope before coordination')
            if abs((self.output[3]-n[1])*signs[0]-(self.output[4]-n[2])*signs[1])>10:
                raise ValueError('Return neck to reference before automatic coordination')
        self.coordinator=(NaturalCoordinator if self.motion_style=='natural' else Coordinator)(self.profile,self.output)
        self.motion_bank.reset(self.output)
        self.tracking=kind;self.mode='running';self.note='Eyes track; neck '+('recenters eyes slowly' if kind=='coordinated' else 'remains at manual target')
    def set_motion_style(self,style):
        if style not in ('natural','legacy'):raise ValueError('Unknown motion style')
        old_kind=self.tracking
        if old_kind in ('eyes','coordinated'):
            row=self._fresh_vision()
            if row['vision']['target'] is None:raise ValueError('Place a face in view before changing motion style')
        self.motion_style=style;self.profile['motion_style']=style
        self.motion_bank.reset(self.output);self.command=list(map(float,self.output))
        if old_kind in ('eyes','coordinated'):self.set_follow(old_kind)
        return style
    def begin_identification(self):
        if self.mode not in ('running','paused'):raise RuntimeError('Start the five-axis session first')
        self.camera_session=None
        if not self.profile.get('neck_position_control_operator_confirmed'):raise ValueError('Confirm position-controlled neck servos first')
        row=self._fresh_vision()
        if row['vision']['target'] is None:raise ValueError('A stationary face is required')
        self.camera_session=row['vision']['source_session_id'];self.tracking='identify';self.mode='running'
        self.ident=dict(phases=identification_plan(self.profile),index=0,start=time.monotonic(),observations={})
        self.ident_result=None;self.note='Keep face and robot still during neck response identification'
    def pause(self):
        self.ident=None;self.tracking='manual';super().pause();self.motion_bank.reset(self.output);self.note='Paused; all five PWM settings held'
    def _visual_tick(self):
        if self.tracking=='manual':return
        try:
            row=self._fresh_vision();v=row['vision']
            if self.tracking=='identify':
                ident=self.ident;i=ident['index'];phase=ident['phases'][i];self.set_targets(phase['target'])
                elapsed=time.monotonic()-ident['start']
                at_target=all(abs(a-b)<=2 for a,b in zip(self.output,phase['target']))
                if at_target:
                    ident.setdefault('settled_since',time.monotonic())
                    settled=time.monotonic()-ident['settled_since']
                    if settled>=.7 and v['target'] is not None:
                        ident['observations'].setdefault(i,{})[v['frame_id']]=list(v['target'])
                else:
                    ident.pop('settled_since',None);settled=0.
                if elapsed>10:raise ValueError('Not enough settled face samples; hold face still and retry')
                if settled<1.5 or len(ident['observations'].get(i,{}))<5:return
                if i+1<len(ident['phases']):
                    ident['index']+=1;ident['start']=time.monotonic();ident.pop('settled_since',None);return
                self.calibration=analyze_identification(ident['phases'],ident['observations'],neck_neutral(self.profile),allow_reference_drift=True)
                self.calibration.update(automatic_yaw_limit_us=100,automatic_pitch_limit_us=100,automatic_yaw_rate_us_per_s=20,automatic_pitch_rate_us_per_s=15)
                self.ident_result=dict(success=True,calibration=self.calibration,camera_session=self.camera_session,camera_setup_signature=self.profile.get('camera_setup_signature'),completed_epoch=time.time(),phase_observations=copy.deepcopy(ident['observations']),phases=copy.deepcopy(ident['phases']))
                self.last_good_record=copy.deepcopy(self.ident_result)
                self.tracking='manual';self.ident=None;self.set_targets(self.reference);self.note='Neck camera response identified; enable coordinated tracking when ready'
            else:
                values=self.coordinator.update(v,self.output,self.calibration if self.tracking=='coordinated' else None)
                if values is not None:
                    if self.tracking=='eyes':values[2:]=self.desired[2:]
                    self.set_targets(values)
        except Exception as exc:
            was_ident=self.tracking=='identify';failed_ident=self.ident;self.tracking='manual';self.ident=None
            self.set_targets(list(self.output));self.command=list(map(float,self.output));self.motion_bank.reset(self.output);self.note='Visual control held: '+str(exc)
            if was_ident:self.ident_result=dict(success=False,error=str(exc),completed_epoch=time.time(),
                phase_observations=copy.deepcopy(failed_ident['observations']) if failed_ident else {},phases=copy.deepcopy(failed_ident['phases']) if failed_ident else [])
    def tick(self,dt):
        if self.mode not in ('running','paused'):return
        try:
            if self.validate_guard_each_tick:self._guard()
            if self.mode=='running':self._visual_tick()
            if not isinstance(dt,(int,float)) or not 0<=dt:raise ValueError('Invalid control interval')
            if self.mode=='running':
                if self.motion_style=='natural' and self.tracking in ('eyes','coordinated'):
                    self.command=self.motion_bank.step(self.desired,dt,self.tracking=='coordinated')
                    values=[round(v) for v in self.command]
                else:
                    rates=[200,100,100,100,100]
                    self.command=[u+max(-rate*min(dt,.1),min(rate*min(dt,.1),target-u)) for u,target,rate in zip(self.command,self.desired,rates)]
                    values=[round(v) for v in self.command]
                    values[1]=max(self.profile.get('eye_vertical_limits_us',[1000,2000])[0],min(self.profile.get('eye_vertical_limits_us',[1000,2000])[1],round(values[1]/10)*10))
            else:values=list(self.hold_pose)
            state=self._send_motion(values)
            self.output=[state['output_us'][ch] for ch in CHANNELS];self.last_state=state;self.motion_frames+=1
        except BaseException as exc:self.mode='fault';self.error=str(exc);self.tracking='manual';self.ident=None
    def _configure_extra_channels(self,state):
        return state  # Subclasses may configure idle outputs, never enable them here.
    def _send_motion(self,values):
        pulses=[0]*22
        for c,u in zip(CHANNELS,values):pulses[c]=u
        seq=self.client.next_sequence();state=self.client.exchange(motion(seq,MASK,pulses))
        if state['sequence']!=seq or state['status']&~5 or state['active_mask']&~MASK:raise RuntimeError('Five-axis motion acknowledgement invalid')
        return state
    def end(self,head_supported=False):
        if self.mode=='idle':return
        if not head_supported:raise ValueError('Support head before disabling PWM')
        try:
            state=self.client.exchange(query(timestamp=int(time.monotonic()*1000)))
            if state['active_mask'] or state['status']:
                state=self.client.exchange(stop(self.client.next_sequence()))
            if state['active_mask'] or state['status']:raise RuntimeError('Five-axis stop not confirmed')
        except BaseException as exc:self.mode='fault';self.error=str(exc);raise
        self.last_state=state;self.mode='idle';self.error='';self.tracking='manual';self.ident=None;self._release()
