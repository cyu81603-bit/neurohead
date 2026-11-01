import sys,time,unittest,threading,tempfile,copy
from pathlib import Path
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'src/pc'));sys.path.insert(0,str(ROOT/'sim'))
from head_session import HeadSession
from test_head_control import profile,Client,Lock,row
class Tests(unittest.TestCase):
    def test_head_session_keeps_all_channels_on_one_worker_while_ui_blocks(self):
        Client.instances=[];Client.fail=False
        p=profile();p['motion_style']='natural'
        s=HeadSession(p,client_factory=Client,lock_factory=lambda _:Lock())
        try:
            self.assertEqual(s.period,.05)
            with patch('eye_follow_panel.verified_command',return_value=[]):s.start()
            s.set_targets([1550,1450,1510,1280,1510]);time.sleep(.45)
            packets=[p for p in Client.instances[-1].packets if p[:2]==b'NH']
            self.assertGreaterEqual(len(packets),5)
            self.assertTrue(all(int.from_bytes(p[8:12],'little')==3|(7<<18) for p in packets))
            self.assertEqual(len(s.output),5);s.pause();held=s.output;time.sleep(.1);self.assertEqual(s.output,held)
            s.end(True)
        finally:
            if s.mode!='idle':s.end(True)
            s.close()
    def test_late_snapshot_and_transient_log_failure_do_not_cancel_tracking(self):
        import head_session as module
        state={'row':row(20,[.1,.1]),'fail':False}
        def read(_):
            if state['fail']:raise OSError('rotation gap')
            return copy.deepcopy(state['row'])
        with patch.object(module,'latest',side_effect=read):
            s=HeadSession(profile(),client_factory=Client,lock_factory=lambda _:Lock())
            try:
                deadline=time.monotonic()+1
                while s.vision_snapshot() is None and time.monotonic()<deadline:time.sleep(.01)
                with patch('eye_follow_panel.verified_command',return_value=[]):s.start()
                s.set_follow('eyes')
                late=copy.deepcopy(state['row']);late['vision']['frame_id']=19;late['vision']['frame_time']-=.06
                state['row']=late;time.sleep(.12);state['fail']=True;time.sleep(.12)
                self.assertEqual(s.extra['tracking'],'eyes');self.assertGreater(s.extra['late_vision_frames'],0)
                self.assertGreater(s.extra['vision_read_errors'],0)
                state['fail']=False;state['row']=row(21,[.2,.2]);time.sleep(.08)
                self.assertEqual(s.extra['tracking'],'eyes');s.end(True)
            finally:
                if s.mode!='idle':s.end(True)
                s.close()
    def test_reader_recovers_from_previous_boot_log_before_following(self):
        import head_session as module
        old=row(90000,[.1,.1],sid='old_boot')
        old['host_monotonic_s']=old['vision']['frame_time']=time.monotonic()+90000
        state={'row':old}
        with patch.object(module,'latest',side_effect=lambda _:copy.deepcopy(state['row'])):
            s=HeadSession(profile(),client_factory=Client,lock_factory=lambda _:Lock())
            try:
                time.sleep(.06);self.assertIsNone(s.vision_snapshot())
                state['row']=row(1,[.1,.1],sid='new_boot')
                deadline=time.monotonic()+1
                while s.vision_snapshot() is None and time.monotonic()<deadline:time.sleep(.01)
                self.assertEqual(s.vision_snapshot()['vision']['source_session_id'],'new_boot')
                with patch('eye_follow_panel.verified_command',return_value=[]):s.start()
                s.set_follow('eyes');time.sleep(.12)
                self.assertEqual(s.extra['tracking'],'eyes');self.assertEqual(s.mode,'running')
                s.end(True)
            finally:
                if s.mode!='idle':s.end(True)
                s.close()
    def test_target_remains_visible_while_worker_has_consumed_mailbox(self):
        s=HeadSession(profile(),client_factory=Client,lock_factory=lambda _:Lock())
        entered=threading.Event();release=threading.Event();original=s._core.set_targets
        def delayed(values):entered.set();release.wait(1);original(values)
        s._core.set_targets=delayed
        wanted=[1550,1450,1520,1250,1520]
        try:
            s.set_targets(wanted);self.assertTrue(entered.wait(1));self.assertEqual(s.desired,wanted)
        finally:release.set();s.close()
    def test_panel_open_is_idle_and_requires_current_operator_confirmation(self):
        import tkinter as tk
        from head_follow_panel import Panel
        Client.instances=[]
        def factory(p):return HeadSession(p,client_factory=Client,lock_factory=lambda _:Lock())
        w=tk.Tk();w.withdraw();w.after=lambda *args:None
        panel=Panel(w,controller_factory=factory)
        try:
            w.update();panel.start();self.assertFalse(Client.instances);self.assertEqual(panel.control.mode,'idle')
            self.assertFalse(panel.ready.get());self.assertEqual(len(panel.control.reference),5)
            self.assertEqual([int(s.get()) for s in panel.sliders],[1500,1500,1500,1270,1500])
            # Redrawing after a preset must not generate a manual takeover callback.
            panel.control.set_targets([1500,1500,1520,1250,1520]);panel.sync(panel.control.desired);w.update()
            self.assertEqual(panel.control.desired,[1500,1500,1520,1250,1520]);self.assertFalse(Client.instances)
            import head_follow_panel as ui
            with tempfile.TemporaryDirectory() as directory:
                temp=Path(directory);(temp/'build').mkdir()
                with patch.object(ui,'ROOT',temp):panel.poll()
            self.assertIn('五路手动',panel.readback.get())
        finally:panel.control.close();w.destroy()
if __name__=='__main__':unittest.main(verbosity=2)