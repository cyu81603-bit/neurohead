"""22-output head plus one-at-a-time facial calibration. Default idle."""
import argparse,json,os,time,tkinter as tk
from tkinter import ttk
from pathlib import Path
import head_follow_panel as head_ui
from face_commission import FaceSession,validate_plan,FACE_CHANNELS
from runtime_logs import write_status
ROOT=Path(__file__).resolve().parents[2]
PLAN=ROOT/'config/face_commission.json'
def load_face_plan():
    p=json.loads(PLAN.read_text(encoding='utf-8-sig'));validate_plan(p['channels']);return p
class FacePanel(head_ui.Panel):
    def __init__(self,window,controller_factory=FaceSession):
        self.plan=load_face_plan()
        def factory(profile):return controller_factory(dict(profile,face_channels=self.plan['channels']))
        super().__init__(window,controller_factory=factory)
        window.title('NeuroHead 22路联调 · 眼颈主控＋面部逐路');self.face_window=tk.Toplevel(window)
        self.face_window.title('面部17路调试 · 一次只输出一路');self.face_window.geometry('1030x800')
        w=self.face_window
        tk.Label(w,text='眉／眼帘／唇／颊／下颚 · 左右按机器人自身',font=('Microsoft YaHei UI',17,'bold')).pack(pady=7)
        tk.Label(w,text='未知中位不能直接扫动。首路可用显式0.2秒候选中位；测试期间眼颈保持、其余16路面部PWM关闭。').pack()
        self.tree=ttk.Treeview(w,columns=('name','channel','pin','candidate','progress'),show='headings',height=17)
        for name,title,width in (('name','部位',200),('channel','CH',60),('pin','J10信号针',100),('candidate','候选中位μs',110),('progress','观察记录',370)):
            self.tree.heading(name,text=title);self.tree.column(name,width=width)
        self.tree.pack(padx=8,pady=7,fill='x');self.tree.bind('<<TreeviewSelect>>',self.select_face)
        self.face_ready=tk.BooleanVar(master=w,value=False);self.decoupled=tk.BooleanVar(master=w,value=False);self.first_loaded=tk.BooleanVar(master=w,value=False)
        tk.Checkbutton(w,text='当前仅此路接线/供电正确，头部托稳，可观察',variable=self.face_ready).pack(anchor='w',padx=12)
        line=tk.Frame(w);line.pack(fill='x',padx=12)
        tk.Checkbutton(line,text='此舵机已脱开连杆／舵盘',variable=self.decoupled).pack(side='left')
        tk.Checkbutton(line,text='无法脱开，明确允许首次0.2秒候选中位',variable=self.first_loaded).pack(side='left',padx=15)
        line=tk.Frame(w);line.pack(pady=5)
        self.candidate=tk.IntVar(master=w,value=1500);self.lo=tk.IntVar(master=w,value=1450);self.hi=tk.IntVar(master=w,value=1550);self.target=tk.IntVar(master=w,value=1500)
        for label,var in (('候选中位',self.candidate),('试验下界',self.lo),('试验上界',self.hi),('本次目标',self.target)):
            tk.Label(line,text=label).pack(side='left');tk.Spinbox(line,from_=600,to=2400,textvariable=var,width=7).pack(side='left',padx=5)
        tk.Button(line,text='保存窗口（控制停止时）',command=self.save_window).pack(side='left',padx=8)
        line=tk.Frame(w);line.pack(pady=5)
        for title,fn in (('候选中位短输出',lambda:self.trial(True)),('目标往返并自动关闭',lambda:self.trial(False)),('只停面部，眼颈保持',self.stop_face)):
            tk.Button(line,text=title,command=fn,width=27).pack(side='left',padx=5)
        line=tk.Frame(w);line.pack(pady=5)
        for title,kind in (('已观察：此中位合适','neutral'),('已观察：该PWM为下限','min'),('已观察：该PWM为上限','max')):
            tk.Button(line,text=title,command=lambda k=kind:self.record(k),width=27).pack(side='left',padx=5)
        line=tk.Frame(w);line.pack(pady=5)
        tk.Label(line,text='增大PWM时实际动作：').pack(side='left');self.direction=tk.StringVar(master=w,value='')
        tk.Entry(line,textvariable=self.direction,width=55).pack(side='left');tk.Button(line,text='保存方向说明',command=lambda:self.record('direction')).pack(side='left',padx=8)
        self.face_status=tk.StringVar(master=w,value='面部尚未输出。选择一路；先在主控窗口确认接线、开始五路控制。')
        tk.Label(w,textvariable=self.face_status,wraplength=990,font=('Microsoft YaHei UI',11)).pack(pady=7)
        tk.Label(w,text='1500μs只是候选值。保存观察由现场操作者确认；不自动认定机械极限。改线先托稳并断外部舵机电源。').pack(pady=5)
        w.protocol('WM_DELETE_WINDOW',self.hide_face);self.refresh_tree();self.tree.selection_set('2');self.select_face()
    def selected(self):
        rows=self.tree.selection()
        if not rows:raise ValueError('Select a face joint')
        return int(rows[0])
    def refresh_tree(self):
        for r in self.plan['channels']:
            progress='中位未知'
            if r.get('mounted_neutral_verified'):progress='装配中位已观察'
            elif r.get('unloaded_center_verified'):progress='空载回中已观察'
            if r.get('observed_min_us') is not None or r.get('observed_max_us') is not None:progress+='；端点%s/%s'%(r.get('observed_min_us'),r.get('observed_max_us'))
            values=(r['label'],r['channel'],r['signal_pin'],r['candidate_neutral_us'],progress)
            if self.tree.exists(str(r['channel'])):self.tree.item(str(r['channel']),values=values)
            else:self.tree.insert('',tk.END,iid=str(r['channel']),values=values)
    def select_face(self,*_):
        try:r=self.plan['channels'][FACE_CHANNELS.index(self.selected())]
        except ValueError:return
        self.candidate.set(r['candidate_neutral_us']);self.lo.set(r['trial_min_us']);self.hi.set(r['trial_max_us']);self.target.set(r['candidate_neutral_us']);self.direction.set(r.get('direction_note',''))
        self.face_ready.set(False);self.decoupled.set(False);self.first_loaded.set(False)
    def face_call(self,fn):
        try:fn()
        except Exception as exc:self.face_status.set('未执行：'+str(exc))
    def save_window(self):
        def action():
            if self.control.mode!='idle':raise ValueError('托稳后在主控结束PWM，再保存；重新开始时应用')
            r=self.plan['channels'][FACE_CHANNELS.index(self.selected())];changed=self.candidate.get()!=r['candidate_neutral_us']
            r.update(candidate_neutral_us=self.candidate.get(),trial_min_us=self.lo.get(),trial_max_us=self.hi.get())
            if changed:r.update(unloaded_center_verified=False,mounted_neutral_verified=False,observed_min_us=None,observed_max_us=None)
            validate_plan(self.plan['channels']);write_status(PLAN,self.plan);self.control.profile=dict(self.control.profile,face_channels=self.plan['channels']);self.refresh_tree();self.face_status.set('试验窗口已保存；不会发动作。下次开始控制时应用。')
        self.face_call(action)
    def trial(self,neutral):
        def action():
            self.control.face_trial(self.selected(),self.candidate.get() if neutral else self.target.get(),self.face_ready.get(),self.decoupled.get(),self.first_loaded.get())
            self.face_status.set('单路测试已开始；到时自动回中/关闭此路。请观察实物。')
        self.face_call(action)
    def stop_face(self):self.face_call(lambda:self.control.stop_face())
    def record(self,kind):
        def action():
            records=self.control.record_face_observation(self.selected(),kind,self.direction.get());self.plan['channels']=records;write_status(PLAN,self.plan);self.control.profile=dict(self.control.profile,face_channels=records);self.refresh_tree();self.face_status.set('现场观察已保存；未发送新动作。')
        self.face_call(action)
    def poll(self):
        super().poll()
        if hasattr(self,'face_status'):
            extra=self.control.extra;t=extra.get('face_trial')
            if t:self.face_status.set('CH%d 单路输出：%s；目标%dμs；总时限%.1fs'%(t['channel'],t['phase'],t['target_us'],t['duration_s']))
            elif extra.get('face_last_trial') and self.face_status.get().startswith('CH'):
                self.face_status.set('本次面部输出已结束，眼颈主控保留。确认实物结果后可保存观察。')
    def hide_face(self):
        if self.control.mode!='idle':self.stop_face();self.face_status.set('面部窗口保留，面部输出已请求关闭。')
        else:self.face_window.withdraw()
def main():
    p=argparse.ArgumentParser();p.add_argument('--self-test',action='store_true');a=p.parse_args();w=tk.Tk()
    if a.self_test:w.withdraw()
    panel=FacePanel(w)
    if a.self_test:
        panel.face_window.withdraw();w.update_idletasks();assert panel.control.mode=='idle' and panel.control.client is None
        assert len(panel.plan['channels'])==17 and not panel.face_ready.get();panel.control.close();w.destroy();print('FACE_PANEL_IDLE_SMOKE_PASS')
    else:w.mainloop()
if __name__=='__main__':main()
