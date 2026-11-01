"""Single-owner facial commissioning. Opening/configuration never enables a face."""
import copy,math,time
from head_control import HeadControl,CHANNELS,MASK
from head_session import HeadSession
from nh22 import config,motion

FACE_CHANNELS=tuple(range(2,18))+(21,)
def validate_plan(rows):
    if len(rows)!=17 or [r.get('channel') for r in rows]!=list(FACE_CHANNELS):raise ValueError('Ordered CH2..17 plus CH21 jaw required')
    if len({r.get('joint') for r in rows})!=17:raise ValueError('Unique facial joints required')
    for r in rows:
        lo,n,hi=(r.get(k) for k in ('trial_min_us','candidate_neutral_us','trial_max_us'))
        if any(type(v) is not int for v in (lo,n,hi)) or not 600<=lo<=n<=hi<=2400:raise ValueError('Invalid candidate/limits')
        if max(n-lo,hi-n)>400:raise ValueError('At most 400us each side per commissioning window')
    return copy.deepcopy(rows)

class FaceCommissionControl(HeadControl):
    def __init__(self,profile,clock=time.monotonic,**kwargs):
        self.clock=clock;self.records=validate_plan(profile['face_channels']);self.trial_state=None;self.last_trial=None
        self.previous_face_bit=0;super().__init__(profile,**kwargs)
    def _configure_extra_channels(self,state):
        self.records=validate_plan(self.profile['face_channels']);self.trial_state=None;self.last_trial=None;self.previous_face_bit=0
        for r in self.records:
            seq=self.client.next_sequence();state=self.client.exchange(config(seq,r['channel'],r['trial_min_us'],r['trial_max_us'],r['candidate_neutral_us'],1,False))
            if state['sequence']!=seq or state['active_mask']:raise RuntimeError('Facial idle configuration rejected')
        return state
    def extra_state(self):
        value=super().extra_state()
        value.update(controller_build='face_commission_v2_22',face_trial=copy.deepcopy(self.trial_state),face_last_trial=copy.deepcopy(self.last_trial),face_records=copy.deepcopy(self.records))
        return value
    def begin_face_trial(self,ch,target,ready=False,decoupled=False,first_loaded=False):
        if self.mode!='running':raise ValueError('Start control and keep it running first')
        if not ready:raise ValueError('Confirm this face signal/power and physical observation')
        if self.trial_state:raise ValueError('Wait for the current face trial or stop it')
        if type(ch) is not int or ch not in FACE_CHANNELS:raise ValueError('Only CH2..17 and CH21 jaw')
        r=self.records[FACE_CHANNELS.index(ch)];n=r['candidate_neutral_us']
        if type(target) is not int or not r['trial_min_us']<=target<=r['trial_max_us']:raise ValueError('Outside this configured trial window')
        unknown=not r.get('mounted_neutral_verified')
        loaded_first=unknown and not decoupled
        if loaded_first and (not first_loaded or target!=n):raise ValueError('Unknown loaded neutral: explicit 0.2s neutral-only trial required')
        duration=.2 if loaded_first else (.5 if target==n else 2*(abs(target-n)/50+.5))
        HeadControl.set_follow(self,'manual')  # One facial joint; gaze/neck held during calibration.
        self.trial_state=dict(channel=ch,target_us=target,neutral_us=n,started=self.clock(),duration_s=duration,
            decoupled=bool(decoupled),loaded_first_pulse=loaded_first,phase='target',status='running',sent_frames=0)
        self.note='Facial CH%d timed trial; other facial channels off'%ch
    def stop_face(self):
        if self.trial_state:
            self.last_trial=dict(self.trial_state,status='aborted',completed=self.clock());self.trial_state=None
        self.note='Face output disabled; eye/neck control retained'
    def pause(self):
        self.stop_face();super().pause()
    def end(self,head_supported=False):
        self.stop_face();return super().end(head_supported)
    def set_follow(self,kind):
        if self.trial_state:raise ValueError('Complete or stop the facial trial before gaze tracking')
        return super().set_follow(kind)
    def _send_motion(self,values):
        face_bit=0;target=None;t=self.trial_state
        if t:
            elapsed=self.clock()-t['started']
            if elapsed>=t['duration_s']:
                self.last_trial=dict(t,status='completed' if t['sent_frames'] else 'not_sent',completed=self.clock());self.trial_state=None
            else:
                face_bit=1<<t['channel'];return_phase=t['target_us']!=t['neutral_us'] and elapsed>=t['duration_s']/2
                t['phase']='return' if return_phase else 'target';target=t['neutral_us'] if return_phase else t['target_us']
        pulses=[0]*22
        for ch,u in zip(CHANNELS,values):pulses[ch]=u
        if face_bit:pulses[t['channel']]=target
        requested=MASK|face_bit;allowed=requested|self.previous_face_bit
        seq=self.client.next_sequence();state=self.client.exchange(motion(seq,requested,pulses))
        if state['sequence']!=seq or state['status']&~5 or state['active_mask']&~allowed:raise RuntimeError('Facial/head acknowledgement invalid')
        # Enable mask takes effect at the next 20ms boundary, so one reply may
        # still contain our previous facial bit while it is being removed.
        if face_bit:t['sent_frames']+=1
        self.previous_face_bit=(state['active_mask']&sum(1<<c for c in FACE_CHANNELS))|face_bit
        return state
    def record_face_observation(self,ch,kind,note=''):
        if ch not in FACE_CHANNELS:raise ValueError('Facial channel required')
        r=self.records[FACE_CHANNELS.index(ch)]
        if kind=='direction':r['direction_note']=str(note);return copy.deepcopy(self.records)
        t=self.last_trial
        if not t or t['channel']!=ch or t['status']!='completed':raise ValueError('A completed trial on this joint is required')
        if kind=='neutral':
            if t['target_us']!=r['candidate_neutral_us']:raise ValueError('Observe the candidate neutral first')
            if t['decoupled']:r['unloaded_center_verified']=True
            else:r['mounted_neutral_verified']=True
        elif kind in ('min','max'):
            if not r.get('mounted_neutral_verified') or t['decoupled']:raise ValueError('Verify assembled neutral before endpoints')
            target=t['target_us'];n=r['candidate_neutral_us']
            if (kind=='min' and target>n) or (kind=='max' and target<n):raise ValueError('Choose the correct PWM endpoint')
            r['observed_min_us' if kind=='min' else 'observed_max_us']=target
        else:raise ValueError('Unknown observation kind')
        r['last_operator_observation_epoch']=time.time();r['full_range_verified']=False
        return copy.deepcopy(self.records)

class FaceSession(HeadSession):
    def __init__(self,profile,**kwargs):super().__init__(profile,core_class=FaceCommissionControl,**kwargs)
    def face_trial(self,ch,target,ready=False,decoupled=False,first_loaded=False):return self._invoke('begin_face_trial',ch,target,ready,decoupled,first_loaded)
    def stop_face(self):return self._invoke('stop_face')
    def record_face_observation(self,ch,kind,note=''):return self._invoke('record_face_observation',ch,kind,note)
