"""Time-based expression intent and verified-pose mixer. No network/device IO."""
import math,random
from head_motion import MotionAxis,blend,clamp
from jaw_motion import FixedPointJaw,fixed_point_plan
from expression_presets import PresetLayer,WinkLayer,wink_signature

def smooth(x):
    x=clamp(x,0,1);return x*x*x*(10+x*(-15+6*x))
def pose_valid(p):
    keys=('neutral_us','min_us','max_us','action_us')
    if any(type(p.get(k)) is not int for k in keys):return False
    n,lo,hi,a=(p[k] for k in keys)
    forbidden=p.get('forbidden_pulses_us',[])
    if not isinstance(forbidden,list) or any(type(u) is not int for u in forbidden):return False
    if any(lo<=u<=hi for u in forbidden):return False
    return 600<=lo<=n<=hi<=2400 and lo<=a<=hi and isinstance(p.get('max_rate_us_per_s'),(int,float)) and 20<=p['max_rate_us_per_s']<=5000 and p.get('range_confirmed') is True

def jaw_probe_valid(p):
    n=p.get('neutral_us')
    return p.get('channel')==21 and p.get('probe_only') is True and p.get('neutral_verified') is True and type(n) is int and 625<=n<=2375 and p.get('min_us')==n-25 and p.get('max_us')==n+25 and 20<=p.get('max_rate_us_per_s',0)<=50 and not p.get('enabled') and not p.get('action_verified') and not p.get('range_confirmed')

def jaw_observed_interval(j):
    if not j or not j.get('operator_open_observed'):raise ValueError('缺少已观察的下颚开合点')
    closed,opened=j.get('closed_us'),j.get('observed_open_us')
    if any(type(v) is not int or not 600<=v<=2400 for v in (closed,opened)) or closed==opened:raise ValueError('下颚开合点无效')
    return min(closed,opened),max(closed,opened)

def approved_poses(config):
    ready={};blocked={}
    for p in config['poses']:
        ch=p['channel']
        if ch not in (*range(2,18),21):raise ValueError('Invalid expression channel')
        if p.get('automatic_inhibited') is True:
            blocked[ch]=p.get('automatic_inhibited_reason','该通道自动输出已屏蔽');continue
        j=config.get('jaw_setup') if ch==21 else None
        if j and j.get('drive_mode')=='fixed_points':
            try:fixed_point_plan(j)
            except ValueError:
                blocked[ch]='下颚两点标定尚未验证或与当前端点不匹配';continue
        try:jaw_bounds=jaw_observed_interval(j) if j else None
        except ValueError:jaw_bounds=None
        if j and not p.get('probe_only') and (not jaw_bounds or not j.get('automatic_committed') or p.get('neutral_us')!=j['closed_us'] or p.get('min_us',0)<jaw_bounds[0] or p.get('max_us',2401)>jaw_bounds[1] or p.get('action_us')!=j['observed_open_us']):blocked[ch]='下颚开合点尚未启用，或超出已观察区间'
        elif p.get('probe_only'):blocked[ch]='仅限下颚小步探查，自动动作已禁用'
        elif not pose_valid(p):blocked[ch]='中位/动作点/范围未确认，或包含已记录卡滞点'
        elif p.get('enabled') is not True or p.get('action_verified') is not True:blocked[ch]='动作方向尚未观察确认'
        else:ready[ch]=dict(p)
    return ready,blocked

class SpeechState:
    def __init__(self):self.generation=0;self.stop()
    def stop(self,token=None):
        if token is not None and token!=self.generation:return
        self.generation+=1;self.kind=None;self.name='';self.started=0.;self.duration=0.;self.frames=[];self.last_energy=0.;self.last_update=0.
    def timeline(self,frames,step,now,name='audio'):
        if not frames or not .005<=step<=.1 or len(frames)*step>300:raise ValueError('Invalid audio timeline')
        if any(not isinstance(e,(int,float)) or not math.isfinite(e) or not 0<=e<=1 for e in frames):raise ValueError('Invalid audio energy')
        self.generation+=1;self.kind='timeline';self.frames=list(frames);self.step=step;self.started=now;self.duration=len(frames)*step;self.name=str(name)[:120];return self.generation
    def external(self,energy,now,name='tts'):
        if not isinstance(energy,(int,float)) or not math.isfinite(energy) or not 0<=energy<=1:raise ValueError('Energy must be 0..1')
        if self.kind!='external' or self.name!=str(name)[:120]:self.generation+=1
        self.kind='external';self.name=str(name)[:120];self.last_energy=energy;self.last_update=now;return self.generation
    def sample(self,now):
        if self.kind=='timeline':
            index=int((now-self.started)/self.step)
            if index<0:return 0.,False
            if index>=len(self.frames):self.stop();return 0.,False
            return self.frames[index],True
        if self.kind=='external':
            if not 0<=now-self.last_update<=.35:self.stop();return 0.,False
            return self.last_energy,True
        return 0.,False

class ExpressionEngine:
    def __init__(self,config,now=0.,seed=None):
        self.config=config;self.poses,self.blocked=approved_poses(config);self.axes={ch:MotionAxis(p['neutral_us'],*sorted((p['neutral_us'],p['action_us']))) for ch,p in self.poses.items()}
        self.fixed_jaw=FixedPointJaw(fixed_point_plan(config.get('jaw_setup')),now) if 21 in self.poses and config.get('jaw_setup',{}).get('drive_mode')=='fixed_points' else None
        self.tracking_active=False
        self.preset=PresetLayer();self.wink=WinkLayer();self.wink_ratio=0.
        fraction=config.get('tracking_blink_fraction',1.)
        if type(fraction) not in (int,float) or not math.isfinite(fraction) or not 0<=fraction<=1:raise ValueError('Invalid tracking blink fraction')
        self.rng=random.Random(seed);self.speech=SpeechState();self.state='off';self.last_time=now;self.energy=0.;self.activity=0.;self.accent=0.;self.last_onset=-100.;self.last_raw_energy=0.
        self.blink=None;self.vision_until=0.;self.stretch_start=None;self.blink_ratio=0.;self.mood='neutral';self.mood_end=0.;self.last_blink=-100.
    def enable(self,now):
        self.state='warming';self.state_since=now;self.last_time=now;self.next_blink=now+self.rng.uniform(3.5,7.5);self.next_stretch=now+(self.rng.uniform(3.5,6) if self.config.get('expression_style','classic')!='classic' else self.rng.uniform(5,9))
    def stop(self,now,immediate=False):
        self.speech.stop();self.blink=None;self.blink_ratio=0.;self.energy=0.
        self.preset.clear();self.wink.event=None;self.wink_ratio=0.;self.mood='neutral';self.mood_end=0.
        if immediate:self.state='off'
        elif self.state!='off':self.state='returning';self.state_since=now
    def blink_once(self,now,clearance_trial=False,direction_trial=False):
        if self.wink.event is not None:return False
        if not {6,8}.issubset(self.poses):return False
        if not self.config.get('blink_pair_verified',True) and not direction_trial:return False
        if self.tracking_active and not self.config.get('camera_clear_blink_verified',True) and not clearance_trial:return False
        if self.blink is not None or now-self.last_blink<1.2:return False
        distance=max(abs(p['action_us']-p['neutral_us']) for ch,p in self.poses.items() if ch in range(6,10))
        rate=min(p['max_rate_us_per_s'] for ch,p in self.poses.items() if ch in range(6,10))
        close=max(.11,1.875*distance/rate,(5.8*distance/(rate*100))**.5,(60*distance/(rate*2000))**(1/3));opening=close*1.25
        self.last_blink=now;self.blink=(now,close,.06,opening);self.vision_until=now+close+.06+opening+.15;return True
    def vision_hold(self,now):return now<self.vision_until
    def wink_once(self,now,intensity=.8,trial=False):
        if self.state!='active':raise ValueError('先开启表情并等待半秒，再试 wink')
        p=self.poses.get(8)
        if p is None:raise ValueError('右上眼帘未确认或已屏蔽')
        approval=self.config.get('wink_right_approval',{})
        if not trial and (approval.get('verified') is not True or approval.get('tracking_clear') is not True or approval.get('pose')!=wink_signature(p)):
            raise ValueError('请先在表情调试窗口试右眼 wink，并确认闭合方向和摄像头画面不被遮挡')
        if self.blink is not None:raise ValueError('请等待眨眼完成')
        self.wink.trigger(now,p,intensity)
    def step(self,now,activity=0.):
        dt=clamp(now-self.last_time,0,.1);self.last_time=now
        if self.state=='off':return {}
        self.activity+=blend(dt,.2)*(clamp(activity,0,1)-self.activity)
        raw,speaking=self.speech.sample(now);closing=.045 if self.config.get('speech_articulation')=='pcm_gaps' else .09;self.energy+=blend(dt,.035 if raw>self.energy else closing)*(raw-self.energy)
        self.accent*=math.exp(-dt/.32)
        if speaking and raw-self.last_raw_energy>.12 and now-self.last_onset>.35:self.accent=max(self.accent,clamp(raw,.25,1));self.last_onset=now
        self.last_raw_energy=raw
        ratios={ch:0. for ch in self.poses}
        style=self.config.get('expression_style','classic');modern=style!='classic'
        strength={'soft':.55,'lively':.8,'active':1.}.get(style,1.)
        speed={'soft':.55,'lively':.8,'active':1.}.get(style,1.)
        if self.state=='warming' and now-self.state_since>=.5:self.state='active'
        if self.state=='active':
            if self.config.get('automatic_blink',True) and now>=self.next_blink:
                self.blink_once(now);self.next_blink=now+self.rng.uniform(*self.config.get('blink_interval_s',[3.5,7.5]))
            if now>=self.next_stretch:self.stretch_start=now;self.next_stretch=now+(self.rng.uniform(3.5,6) if self.config.get('expression_style','classic')!='classic' else self.rng.uniform(5,9))
            stretch=0.
            if self.stretch_start is not None:
                phase=(now-self.stretch_start)/self.config.get('stretch_duration_s',2.4)
                if 0<=phase<=1:stretch=math.sin(math.pi*phase)**2*(.5 if modern else .2)
            mood=.18 if now<self.mood_end and self.mood in ('happy','curious','engaged') else 0.
            for ch in self.poses:
                if ch in range(2,6):
                    local_mood=(.22 if ch in (2,4) else .04) if now<self.mood_end and self.mood=='sad' else mood
                    extra_voice=.30*self.energy if self.config.get('speech_motion_gain')=='large' else 0.
                    ratios[ch]=clamp((stretch+(.22 if modern else .14)*self.activity+(.75 if modern else .55)*self.accent+local_mood+extra_voice)*strength,0,.95 if modern else .85)
                elif ch==21:ratios[ch]=clamp(self.energy*(.98 if self.config.get('speech_motion_gain')=='large' else .9),0,.98)
                elif ch in range(10,14):ratios[ch]=clamp(self.energy*(1. if self.config.get('speech_motion_gain')=='large' else .72 if modern else .32)*strength,0,1. if self.config.get('speech_motion_gain')=='large' else .8 if modern else .4)
                elif ch in range(14,18):ratios[ch]=clamp((mood*.8+(.40 if self.config.get('speech_motion_gain')=='large' else .22 if modern else .08)*self.accent+(.28*self.energy if self.config.get('speech_motion_gain')=='large' else .10*self.energy if self.config.get('speech_articulation')=='pcm_gaps' else 0))*strength,0,.70 if self.config.get('speech_motion_gain')=='large' else .38 if modern else .22)
            self.blink_ratio=0.
            if self.blink:
                start,closing,hold,opening=self.blink;t=now-start
                if t<closing:self.blink_ratio=smooth(t/closing)
                elif t<closing+hold:self.blink_ratio=1.
                elif t<closing+hold+opening:self.blink_ratio=1-smooth((t-closing-hold)/opening)
                else:self.blink=None
            for ch in range(6,10):
                if ch in ratios:
                    ratio=self.blink_ratio*(self.config.get('tracking_blink_fraction',1.) if self.tracking_active else 1.)
                    ratios[ch]=0. if ch in (7,9) and not self.config.get('blink_lower_lids',True) else ratio
            layer,mix=self.preset.sample(now)
            for ch,value in layer.items():
                if ch not in ratios:continue
                base=ratios[ch];ratios[ch]=base*(1-mix)+value
                # Speech articulation retains priority over a static facial pose.
                if speaking and ch in range(10,18):ratios[ch]=max(base,ratios[ch])
            self.wink_ratio=self.wink.sample(now)
            if self.wink.event is not None or self.wink_ratio:
                if 8 in ratios:ratios[8]=self.wink_ratio
        output={}
        for ch,p in self.poses.items():
            target=p['neutral_us']+(p['action_us']-p['neutral_us'])*ratios[ch];rate=p['max_rate_us_per_s']*(speed if ch not in range(6,10) and ch!=21 else 1)
            if ch==21 and self.fixed_jaw:
                value=self.fixed_jaw.step(now,self.energy,speaking,self.state=='active');self.axes[ch].reset(value)
            elif ch in range(6,10) and self.state=='active':value=target;self.axes[ch].reset(value)
            else:value=self.axes[ch].step(target,dt,rate,rate*12,rate*240)
            output[ch]=round(clamp(value,p['min_us'],p['max_us']))
        close_held=self.state!='returning' or not self.fixed_jaw or now-self.state_since>=self.fixed_jaw.plan['close_hold_s']
        if self.state=='returning' and close_held and all(abs(self.axes[ch].position-p['neutral_us'])<1 for ch,p in self.poses.items()):self.state='off';return {}
        return output
