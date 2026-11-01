"""One-click AX7020 power-cycle recovery. No automatic servo configuration/motion."""
import argparse,contextlib,json,os,queue,secrets,shutil,subprocess,sys,threading,time
from pathlib import Path
for stream in (sys.stdout,sys.stderr):
    if stream is not None and hasattr(stream,'reconfigure'):stream.reconfigure(encoding='utf-8',errors='replace')
ROOT=Path(__file__).resolve().parents[2]
PYTHON=Path(r'F:\NeuroHead\workspace\neurohead_fpga_2026\build\pybullet_env\python.exe')
PYTHONW=PYTHON.with_name('pythonw.exe')
XSCT=Path(r'F:\2026.1\Vitis\bin\xsdb.bat')
NO_WINDOW=getattr(subprocess,'CREATE_NO_WINDOW',0)
class RecoveryError(RuntimeError):pass
class CommunicationError(RecoveryError):pass

def live_controllers(root=ROOT,now=None):
    now=time.time() if now is None else now;owners=[]
    roots=[Path(root)]
    if Path(root).resolve()==ROOT.resolve():roots.extend([Path(r'F:\NeuroHead\builds\nh21_20261024'),Path(r'F:\NeuroHead\builds\nh22_20261028')])
    head_status=[p for folder in roots for p in (folder/'build').glob('head_runtime_*.json')]
    for p in head_status:
        try:r=json.loads(p.read_text(encoding='utf-8'))
        except (OSError,ValueError):continue
        if 0<=now-r.get('updated_epoch',0)<3 and r.get('mode') in ('running','paused','fault'):
            owners.append(dict(pid=r.get('owner_pid'),mode=r['mode']))
    for p in [p for folder in roots for p in (folder/'build').glob('neck_manual_runtime_*.json')]:
        try:r=json.loads(p.read_text(encoding='utf-8'))
        except (OSError,ValueError):continue
        if 0<=now-r.get('updated_epoch',0)<3 and r.get('mode') in ('running','paused','fault'):
            owners.append(dict(pid=r.get('owner_pid'),mode=r['mode']))
    return owners

def powershell_path(root=ROOT):
    cfg=json.loads((Path(root)/'config/restart.json').read_text(encoding='utf-8-sig'))
    candidates=[shutil.which('pwsh'),cfg.get('powershell7_path'),str(Path(os.environ.get('ProgramFiles','C:/Program Files'))/'PowerShell/7/pwsh.exe')]
    for value in candidates:
        if value and Path(value).is_file():return str(value)
    raise RecoveryError('找不到PowerShell 7，请检查config/restart.json中的路径。')

def run_command(args,timeout=120):
    try:return subprocess.run([str(a) for a in args],cwd=ROOT,env=dict(os.environ,PYTHONUTF8='1',PYTHONIOENCODING='utf-8'),capture_output=True,text=True,encoding='utf-8',errors='replace',timeout=timeout,creationflags=NO_WINDOW)
    except subprocess.TimeoutExpired as exc:raise RecoveryError('步骤超时，恢复已停止；请保持舵机断电。') from exc

class BoardRecovery:
    def __init__(self,root=ROOT,runner=run_command,notify=lambda text:None,controllers=None,lock_factory=None):
        self.root=Path(root);self.runner=runner;self.notify=notify;self.controllers=controllers or (lambda:live_controllers(self.root))
        if lock_factory is None:
            from eye_camera_feedback import acquire_run_lock
            lock_factory=acquire_run_lock
        self.lock_factory=lock_factory;self.log_path=None;self.trace=None;self.shell=None
    def log(self,message):
        self.notify(message)
        if self.log_path:
            with self.log_path.open('a',encoding='utf-8') as handle:handle.write(message+'\n')
    def command(self,args,label,timeout=120):
        self.log(label);result=self.runner(args,timeout=timeout)
        output=(result.stdout or '')+'\n'+(result.stderr or '')
        if output.strip():self.log(output.strip())
        return result,output
    def ps(self,script,*args):return [self.shell,'-NoProfile','-ExecutionPolicy','Bypass','-File',self.root/'scripts'/script,*args]
    def check_dependencies(self):
        self.shell=powershell_path(self.root)
        required=[PYTHON,PYTHONW,XSCT,self.root/'scripts/load_22.ps1',self.root/'scripts/ensure_restart_network.ps1',self.root/'scripts/recover_cold_network.tcl',self.root/'src/pc/probe_board.py',self.root/'build/release_manifest.json']
        for p in required:
            if not p.is_file():raise RecoveryError('缺少依赖文件：'+str(p))
    def query(self,unconfigured=True):
        out=self.trace/('query_'+str(time.time_ns())+'.json')
        args=[PYTHON,self.root/'src/pc/probe_board.py','--count','10','--out',out]
        if unconfigured:args.append('--expect-disabled')
        result,text=self.command(args,'检查板卡通信及PWM关闭状态',timeout=20)
        if result.returncode:
            if 'TimeoutError' in text or 'timed out' in text:raise CommunicationError('板卡查询超时')
            raise RecoveryError('板卡查询失败；没有执行额外复位。详见日志。')
        try:r=json.loads(out.read_text(encoding='utf-8'));state=r['last']
        except (OSError,ValueError,KeyError) as exc:raise RecoveryError('缺少本次查询的有效结果。') from exc
        if (not r.get('read_only') or r.get('motion_commands_sent')!=0 or r.get('configuration_commands_sent')!=0 or r.get('successful_queries')!=10):raise RecoveryError('查询结果校验失败。')
        if state.get('status') or state.get('active_mask') or (unconfigured and state.get('configured_mask')):raise RecoveryError('板卡并非PWM关闭状态，请先结束原控制会话。')
        return r,out
    def recover(self,servo_off=False,signals_off=False,board_ready=False,check_only=False):
        if not check_only and not (servo_off and signals_off and board_ready):raise RecoveryError('请先确认舵机断电、所有PWM拔开、板卡/JTAG/网线已准备好。')
        owners=self.controllers()
        if owners:raise RecoveryError('已有控制窗口正在运行/保持，请托稳后先结束该会话：'+str(owners))
        self.check_dependencies();self.trace=self.root/'build/restarts'/(str(time.time_ns())+'_'+secrets.token_hex(4));self.trace.mkdir(parents=True)
        self.log_path=self.trace/'recovery.log'
        try:lock=self.lock_factory(self.root/'build/eye_feedback.lock')
        except OSError as exc:raise RecoveryError('控制锁被占用，请先结束原控制会话。') from exc
        with lock:
            if self.controllers():raise RecoveryError('控制会话刚刚启动，已中止恢复。')
            result,_=self.command(self.ps('ensure_restart_network.ps1',*(['-CheckOnly'] if check_only else [])),'检查专用有线网络；需要时会弹出Windows管理员提示',timeout=65)
            if result.returncode:raise RecoveryError('专用网卡未准备好；请看日志中的网线、IPv4或管理员权限提示。')
            cold=False
            if not check_only:
                result,text=self.command(self.ps('load_22.ps1','-ServoPowerOff','-SignalsDisconnected','-RecoveryAssetsOnly'),'校验文件并通过JTAG加载板卡，保持舵机断电',timeout=120)
                if result.returncode or 'MONITOR_BINARY_JTAG_LAUNCHED:' not in text:raise RecoveryError('JTAG加载未成功，保持舵机断电，不会打开控制会话。')
            try:report,query_path=self.query(unconfigured=not check_only)
            except CommunicationError:
                if check_only:raise
                result,text=self.command([XSCT,self.root/'scripts/recover_cold_network.tcl'],'执行一次冷启动网络恢复（舵机仍断电）',timeout=30)
                if result.returncode or 'COLD_START_RESUME_OK' not in text:raise RecoveryError('冷启动网络恢复失败，请保持舵机断电。')
                cold=True;report,query_path=self.query(unconfigured=True)
            result=dict(success=True,check_only=check_only,cold_network_recovered=cold,query_path=str(query_path),successful_queries=10,pwm_disabled=True,configuration_commands_sent=0,motion_commands_sent=0,log_path=str(self.log_path))
            (self.trace/'result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
            self.log('恢复完成：通信10次通过，PWM关闭；尚未发舵机配置或动作。')
            return result

def open_frontend(kind,root=ROOT):
    root=Path(root);now=time.time()
    for p in (root/'build').glob('head_runtime_*.json'):
        try:r=json.loads(p.read_text(encoding='utf-8'))
        except (OSError,ValueError):continue
        match=(r.get('controller_build','').startswith('lifelike_v') and (not (root/'integration/embodied/embodied_app.py').exists() or r.get('integration_revision')==63) if kind=='life' else r.get('controller_build')=='face_commission_v2_22' if kind=='face' else ('motion_style' in r and not r.get('controller_build')))
        if match and r.get('mode')=='idle' and 0<=now-r.get('updated_epoch',0)<3:return dict(reused_pid=r.get('owner_pid'))
    path=root/'src/pc'/('lifelike_panel.py' if kind=='life' else 'face_commission_panel.py' if kind=='face' else 'head_follow_panel.py')
    python=PYTHONW
    if kind=='life' and (root/'integration/embodied/embodied_app.py').exists():
        path=root/'integration/embodied/embodied_app.py'
        python=Path(r'F:\NeuroHead\environments\embodied_20261029\Scripts\pythonw.exe')
    process=subprocess.Popen([str(python),str(path)],cwd=root,creationflags=NO_WINDOW)
    return dict(opened_pid=process.pid)

class RestartPanel:
    def __init__(self,window):
        import tkinter as tk
        from tkinter import ttk
        self.window=window;self.events=queue.Queue();self.busy=False;self.last_result=None
        window.title('NeuroHead AX7020 · 断电恢复启动器');window.geometry('850x640')
        tk.Label(window,text='AX7020 断电恢复',font=('Microsoft YaHei UI',22,'bold')).pack(pady=14)
        tk.Label(window,text='重新上电后：恢复专用网卡 → 校验并加载位流/固件 → 检查通信 → 打开空闲调试界面').pack()
        self.off=tk.BooleanVar(master=window,value=False);self.signals=tk.BooleanVar(master=window,value=False);self.board=tk.BooleanVar(master=window,value=False)
        for label,var in (('头部已托稳，外部舵机电源已关闭',self.off),('所有已连接的PWM信号线已拔开',self.signals),('只给AX7020上电，JTAG和网线已连接',self.board)):
            tk.Checkbutton(window,text=label,variable=var).pack(anchor='w',padx=35,pady=4)
        row=tk.Frame(window);row.pack(pady=10);tk.Label(row,text='恢复后打开：').pack(side='left')
        preference=json.loads((ROOT/'config/restart.json').read_text(encoding='utf-8-sig')).get('default_frontend','face')
        self.frontend=tk.StringVar(master=window,value='活人感／语音与表情' if preference=='life' else '眼球＋脖子跟随' if preference=='head' else '22路／面部逐路调试')
        ttk.Combobox(row,textvariable=self.frontend,values=['活人感／语音与表情','22路／面部逐路调试','眼球＋脖子跟随'],state='readonly',width=28).pack(side='left')
        row=tk.Frame(window);row.pack(pady=8)
        self.load_button=tk.Button(row,text='重新加载板卡并打开界面',command=lambda:self.start(False),width=29);self.load_button.pack(side='left',padx=5)
        self.check_button=tk.Button(row,text='板卡已加载：只检查并打开界面',command=lambda:self.start(True),width=32);self.check_button.pack(side='left',padx=5)
        self.status=tk.StringVar(master=window,value='尚未操作。加载后PWM保持关闭，中位和标定文件保留。')
        tk.Label(window,textvariable=self.status,wraplength=810,font=('Microsoft YaHei UI',11)).pack(pady=10)
        self.log_widget=tk.Text(window,height=13,width=110,state='disabled');self.log_widget.pack(padx=12,fill='both',expand=True)
        tk.Label(window,text='恢复成功后再接回信号和舵机供电，并在调试窗口显式开始。不会自动追踪或恢复面部试验。').pack(pady=8)
        window.protocol('WM_DELETE_WINDOW',self.close);window.after(100,self.poll)
    def start(self,check_only):
        if self.busy:return
        if not check_only and not (self.off.get() and self.signals.get() and self.board.get()):self.status.set('请先完成并勾选上面的三项现场确认。');return
        kind='life' if self.frontend.get().startswith('活人感') else 'face' if self.frontend.get().startswith('22') else 'head'
        pref_path=ROOT/'config/restart.json';pref=json.loads(pref_path.read_text(encoding='utf-8-sig'));pref['default_frontend']=kind;pref_path.write_text(json.dumps(pref,indent=2),encoding='utf-8')
        flags=(self.off.get(),self.signals.get(),self.board.get());self.busy=True
        self.load_button.configure(state='disabled');self.check_button.configure(state='disabled')
        def work():
            engine=BoardRecovery(notify=lambda line:self.events.put(('log',line)))
            try:
                result=engine.recover(*flags,check_only=check_only);result.update(frontend=open_frontend(kind));self.events.put(('done',result))
            except Exception as exc:self.events.put(('error',str(exc)+'\n日志：'+str(engine.log_path or '尚未加载')))
        threading.Thread(target=work,name='board-recovery',daemon=True).start()
    def poll(self):
        while True:
            try:kind,value=self.events.get_nowait()
            except queue.Empty:break
            if kind=='log':
                self.status.set(value.splitlines()[0][:120]);self.log_widget.configure(state='normal');self.log_widget.insert('end',value+'\n');self.log_widget.see('end');self.log_widget.configure(state='disabled')
            else:
                self.busy=False;self.load_button.configure(state='normal');self.check_button.configure(state='normal')
                if kind=='done':self.last_result=value;self.status.set('恢复成功，PWM关闭。调试界面已打开／保留；请按界面步骤接回舵机。')
                else:self.status.set('未完成：'+value)
        self.window.after(100,self.poll)
    def close(self):
        if self.busy:self.status.set('正在加载或检查，请等待结果；舵机继续保持断电。')
        else:self.window.destroy()

def main():
    p=argparse.ArgumentParser();p.add_argument('--recover',action='store_true');p.add_argument('--check-only',action='store_true');p.add_argument('--servo-power-off',action='store_true');p.add_argument('--signals-disconnected',action='store_true');p.add_argument('--board-ready',action='store_true');p.add_argument('--no-open',action='store_true');p.add_argument('--frontend',choices=['face','head','life'],default='face');p.add_argument('--self-test',action='store_true');a=p.parse_args()
    if a.recover or a.check_only:
        result=BoardRecovery(notify=print).recover(a.servo_power_off,a.signals_disconnected,a.board_ready,a.check_only)
        if not a.no_open:result.update(frontend=open_frontend(a.frontend))
        print(json.dumps(result,ensure_ascii=False));return
    import tkinter as tk
    w=tk.Tk()
    if a.self_test:w.withdraw()
    panel=RestartPanel(w)
    if a.self_test:
        w.update_idletasks();assert not panel.busy and panel.last_result is None and not panel.off.get() and not panel.signals.get();w.destroy();print('RESTART_PANEL_IDLE_SMOKE_PASS')
    else:w.mainloop()
if __name__=='__main__':main()
