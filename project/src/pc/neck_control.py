"""Manual neck-only control. Pause and transport faults preserve neck holding.
Opening an interface must not connect or enable PWM.
"""
import hashlib,time
from neck_presets import neck_neutral
from nh22 import config,motion,query,stop
from neck_transport import NeckClient as Client
from neck_yaw_midpoint import ROOT,GUARD,GUARD_HASH,ALLOWED_IDLE_CONFIG,acquire_run_lock
CHANNELS=(18,19,20)
MASK=7<<18
class NeckControl:
    def __init__(self,profile,client_factory=Client,lock_factory=acquire_run_lock,validate_guard_each_tick=True):
        self.profile=profile;self.client_factory=client_factory;self.lock_factory=lock_factory;self.validate_guard_each_tick=validate_guard_each_tick
        self.client=None;self.lock=None;self.mode='idle';self.reference=neck_neutral(profile);self.desired=list(self.reference)
        self.command=[float(v) for v in self.reference];self.output=list(self.reference);self.hold_pose=list(self.reference);self.error='';self.last_state=None
    def set_targets(self,values):
        if len(values)!=3 or any(type(v) is not int or not 1100<=v<=1900 for v in values):
            raise ValueError('neck targets must be three integer PWM values in 1100..1900')
        self.desired=list(values)
    def _guard(self):
        if hashlib.sha256(GUARD.read_bytes()).hexdigest()!=GUARD_HASH:raise RuntimeError('original eye guard changed')
    def _release(self):
        if self.client:self.client.close();self.client=None
        if self.lock:self.lock.close();self.lock=None
    def start(self):
        if self.mode=='running':return
        if self.mode=='paused':self.mode='running';return
        if self.mode!='idle':raise RuntimeError('end this session before restarting after a fault')
        p=self.profile
        if not (p.get('yaw_reference_operator_verified') and p.get('pair_first_output_no_abnormal_operator_confirmed')):
            raise ValueError('observed neck reference and no-abnormal first output required')
        self.reference=neck_neutral(p)
        self._guard();self.lock=self.lock_factory(ROOT/'build/eye_feedback.lock')
        try:
            self.client=self.client_factory(bind='192.168.10.10',timeout=.1)
            state=self.client.exchange(query())
            if state['status'] or state['active_mask'] or state['configured_mask']&~ALLOWED_IDLE_CONFIG:
                raise RuntimeError('board occupied or not ready; no actuator writes sent')
            for c,neutral in zip(CHANNELS,self.reference):
                seq=self.client.next_sequence();state=self.client.exchange(config(seq,c,1100,1900,neutral,2,True))
                if state['sequence']!=seq or state['active_mask']:raise RuntimeError('idle neck hold configuration rejected')
        except BaseException:
            self._release();raise
        self.command=[float(v) for v in self.reference];self.output=list(self.reference);self.mode='running';self.error='';self.last_state=state
    def pause(self):
        if self.mode=='running':
            self.hold_pose=list(self.output);self.command=[float(v) for v in self.output]
            self.desired=list(self.output);self.mode='paused'
    def tick(self,dt):
        if self.mode not in ('running','paused'):return
        try:
            if self.validate_guard_each_tick:self._guard()
            if not isinstance(dt,(float,int)) or dt<0:raise ValueError('invalid control interval')
            if self.mode=='running':
                distance=100*min(float(dt),.1)
                self.command=[u+max(-distance,min(distance,t-u)) for u,t in zip(self.command,self.desired)]
                values=[round(v) for v in self.command]
            else:values=list(self.hold_pose)
            pulses=[0]*22
            for c,u in zip(CHANNELS,values):pulses[c]=u
            seq=self.client.next_sequence()
            state=self.client.exchange(motion(seq,MASK,pulses))
            if state['sequence']!=seq or state['status']&~5 or state['active_mask']&~MASK:
                raise RuntimeError('neck motion or holding acknowledgement invalid')
            self.output=[state['output_us'][c] for c in CHANNELS];self.last_state=state
        except BaseException as exc:
            # Each neck channel was configured hold-on-watchdog. Do not send NS
            # on a transport/control fault: global stop would drop its holding.
            self.mode='fault';self.error=str(exc)
    def end(self,head_supported=False):
        if self.mode=='idle':return
        if not head_supported:raise ValueError('head support required before disabling neck PWM')
        try:
            state=self.client.exchange(query(timestamp=int(time.monotonic()*1000)))
            if state['status']==0 and state['active_mask']==0:
                self.last_state=state;self.mode='idle';self.error='';self._release();return
            seq=self.client.next_sequence();state=self.client.exchange(stop(seq))
            if state['sequence']!=seq or state['status'] or state['active_mask']:
                raise RuntimeError('PWM stop not acknowledged')
        except BaseException as exc:
            self.mode='fault';self.error=str(exc);raise
        self.last_state=state;self.mode='idle';self.error='';self._release()