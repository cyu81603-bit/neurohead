"""Own all neck UDP IO on a dedicated heartbeat thread, independent of Tk."""
import copy,queue,threading,time
from concurrent.futures import Future,TimeoutError
from neck_control import NeckControl
from neck_transport import NeckClient
from neck_yaw_midpoint import acquire_run_lock
from nh22 import query
class NeckSession:
    def __init__(self,profile,client_factory=NeckClient,lock_factory=acquire_run_lock,period=.05,core_factory=NeckControl):
        self._core=core_factory(profile,client_factory=client_factory,lock_factory=lock_factory,validate_guard_each_tick=False)
        self._mutex=threading.Lock();self._queue=queue.Queue();self._wake=threading.Event();self._stop=threading.Event()
        self._profile=copy.deepcopy(profile);self._pending_profile=None;self._pending_targets=None;self._inflight_targets=None;self._state={}
        self.period=period;self.max_active_gap_s=0.;self.tick_count=0;self._publish()
        self._worker=threading.Thread(target=self._run,name='neck-heartbeat',daemon=True)
        self._guard=threading.Thread(target=self._guard_monitor,name='neck-guard-monitor',daemon=True)
        self._worker.start();self._guard.start()
    def _publish(self):
        c=self._core
        state=dict(mode=c.mode,error=c.error,desired=list(c.desired),output=list(c.output),reference=list(c.reference),
            last_state=copy.deepcopy(c.last_state),connected=c.client is not None,tick_count=self.tick_count,max_active_gap_s=self.max_active_gap_s)
        if hasattr(c,'extra_state'):state['extra']=c.extra_state()
        with self._mutex:self._state=state;self._inflight_targets=None
    def _get(self,key):
        with self._mutex:return copy.deepcopy(self._state[key])
    @property
    def mode(self):return self._get('mode')
    @property
    def error(self):return self._get('error')
    @property
    def output(self):return self._get('output')
    @property
    def reference(self):return self._get('reference')
    @property
    def last_state(self):return self._get('last_state')
    @property
    def client(self):return True if self._get('connected') else None
    @property
    def desired(self):
        with self._mutex:
            value=self._pending_targets if self._pending_targets is not None else self._inflight_targets
            return list(value) if value is not None else list(self._state['desired'])
    @property
    def profile(self):
        with self._mutex:return copy.deepcopy(self._profile)
    @profile.setter
    def profile(self,value):
        with self._mutex:self._profile=copy.deepcopy(value);self._pending_profile=copy.deepcopy(value)
        self._wake.set()
    def set_targets(self,values):
        if len(values)!=3 or any(type(v) is not int or not 1100<=v<=1900 for v in values):raise ValueError('invalid physical neck targets')
        with self._mutex:self._pending_targets=list(values)
        self._wake.set()
    def _invoke(self,name,*args):
        future=Future();cancel=threading.Event();self._queue.put((name,args,future,cancel));self._wake.set()
        try:return future.result(timeout=2.)
        except TimeoutError:
            cancel.set();raise RuntimeError('control action timed out; pending start will not enable late motion')
    def start(self):return self._invoke('start')
    def pause(self):return self._invoke('pause')
    def end(self,head_supported=False):return self._invoke('end',head_supported)
    def tick(self,dt):pass  # Tk polling never sends IO; the heartbeat worker owns it.
    def close(self):
        if self.mode!='idle':raise RuntimeError('support and end neck control before closing')
        self._stop.set();self._wake.set();self._worker.join(.5);self._guard.join(.5)
    def _guard_monitor(self):
        while not self._stop.wait(.5):
            if self.mode not in ('running','paused'):continue
            try:self._core._guard()
            except Exception as exc:
                self._queue.put(('_fault',(str(exc),),None,threading.Event()));self._wake.set()
    def _run(self):
        last_tick=time.monotonic();next_tick=last_tick;last_active=None
        while not self._stop.is_set():
            self._wake.clear()
            with self._mutex:
                profile=self._pending_profile;targets=self._pending_targets
                self._pending_profile=None;self._pending_targets=None
                if targets is not None:self._inflight_targets=list(targets)
            if profile is not None:self._core.profile=profile
            if targets is not None:self._core.set_targets(targets)
            while True:
                try:name,args,future,cancel=self._queue.get_nowait()
                except queue.Empty:break
                if cancel.is_set():continue
                was_idle=self._core.mode=='idle'
                try:
                    if name=='_fault':self._core.mode='fault';self._core.error=args[0];result=None
                    else:result=getattr(self._core,name)(*args)
                    if cancel.is_set() and name=='start' and was_idle:
                        # Start configuration cannot emit NH. A canceled late start
                        # releases its idle resources before any heartbeat is sent.
                        self._core.mode='idle';self._core._release()
                    self._publish()
                    if future is not None and not future.done():future.set_result(result)
                except BaseException as exc:
                    self._publish()
                    if future is not None and not future.done():future.set_exception(exc)
            now=time.monotonic()
            if now>=next_tick:
                active=self._core.mode in ('running','paused')
                if active and last_active is not None:self.max_active_gap_s=max(self.max_active_gap_s,now-last_active)
                last_active=now if active else None
                previous_mode=self._core.mode;self._core.tick(now-last_tick);self.tick_count+=1
                if previous_mode in ('running','paused') and self._core.mode=='fault' and self._core.client:
                    try:
                        s=self._core.client.exchange(query(timestamp=int(time.monotonic()*1000)))
                        self._core.last_state=s;self._core.output=[s['output_us'][ch] for ch in getattr(self._core,'channels',(18,19,20))]
                    except Exception:pass
                self._publish();last_tick=now;next_tick=now+self.period
            self._wake.wait(max(0,next_tick-time.monotonic()))