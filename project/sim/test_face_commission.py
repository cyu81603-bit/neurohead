import copy,contextlib,json,re,struct,sys,time,unittest
from pathlib import Path
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1];sys.path[:0]=[str(ROOT/'src/pc'),str(ROOT/'sim')]
from face_commission import FaceCommissionControl,FaceSession,validate_plan,FACE_CHANNELS
from head_control import HeadControl,MASK
from test_head_control import profile,Client,Lock

def plan():
    rows=json.loads((ROOT/'config/face_commission.json').read_text(encoding='utf-8'))['channels']
    for r in rows:r.update(candidate_neutral_us=1500,trial_min_us=1450,trial_max_us=1550,unloaded_center_verified=False,mounted_neutral_verified=False,observed_min_us=None,observed_max_us=None)
    return rows
class Board(Client):
    instances=[]
    def __init__(self,**kwargs):super().__init__(**kwargs);self.configured=0;self.config_rows={}
    def exchange(self,p):
        if p[:2]==b'NC':self.configured|=1<<p[8];self.config_rows[p[8]]=p
        r=super().exchange(p);r['configured_mask']=self.configured;return r
class FaceTests(unittest.TestCase):
    def make(self):
        Board.instances=[];Board.fail=False;self.clock=[0.]
        c=FaceCommissionControl(dict(profile(),face_channels=plan()),clock=lambda:self.clock[0],client_factory=Board,lock_factory=lambda _:Lock());c._guard=lambda:None;return c
    def start(self,c):
        with patch('eye_follow_panel.verified_command',return_value=[]):c.start()
    def test_open_idle_no_packets_and_ordered_physical_pin_map(self):
        c=self.make();c.tick(.05);self.assertFalse(Board.instances)
        xdc=(ROOT/'board/ax7020_zynq_ports_template.xdc').read_text(encoding='utf-8')
        for r in plan():
            self.assertIn('# channel %d: J10 pin%d'%(r['channel'],r['signal_pin']),xdc)
            self.assertIn('PACKAGE_PIN %s [get_ports {pwm_0[%d]}]'%(r['package_pin'],r['channel']),xdc)
            self.assertFalse(r['mounted_neutral_verified'])
    def test_idle_config_all_channels_but_start_enables_only_head(self):
        c=self.make();self.start(c);b=Board.instances[-1]
        self.assertEqual(b.configured,(1<<22)-1);self.assertFalse(any(p[:2]==b'NH' for p in b.packets))
        for ch in FACE_CHANNELS:self.assertEqual(b.config_rows[ch][9],0)
        c.tick(.05);self.assertEqual(c.last_state['active_mask'],MASK)
        self.assertTrue(all(p[:2]!=b'NH' or int.from_bytes(p[8:12],'little')==MASK for p in b.packets));c.end(True)
    def test_unknown_loaded_only_explicit_short_neutral(self):
        c=self.make();self.start(c)
        for target,ready,first in ((1500,False,True),(1500,True,False),(1510,True,True)):
            with self.assertRaises(ValueError):c.begin_face_trial(2,target,ready,False,first)
        c.begin_face_trial(2,1500,True,False,True);self.assertEqual(c.trial_state['duration_s'],.2)
        c.tick(.05);self.assertEqual(c.last_state['active_mask'],MASK|4)
        self.clock[0]=.21;c.tick(.05);self.assertEqual(c.last_state['active_mask'],MASK);self.assertEqual(c.last_trial['status'],'completed');c.end(True)
    def test_elapsed_trial_never_sent_cannot_be_recorded_as_observed(self):
        c=self.make();self.start(c);c.begin_face_trial(2,1500,True,False,True);self.clock[0]=1;c.tick(.05)
        self.assertEqual(c.last_trial['status'],'not_sent')
        with self.assertRaises(ValueError):c.record_face_observation(2,'neutral')
        c.end(True)
    def test_selected_only_return_and_face_mask_removed(self):
        c=self.make();self.start(c);c.begin_face_trial(3,1450,True,True)
        c.tick(.05);self.assertEqual(c.last_state['active_mask'],MASK|8);self.assertEqual(c.last_state['output_us'][3],1450)
        with self.assertRaises(ValueError):c.begin_face_trial(4,1500,True,True)
        self.clock[0]=1.6;c.tick(.05);self.assertEqual(c.last_state['output_us'][3],1500)
        self.clock[0]=3.1;c.tick(.05);self.assertEqual(c.last_state['active_mask'],MASK)
        for p in (p for p in Board.instances[-1].packets if p[:2]==b'NH'):
            face=int.from_bytes(p[8:12],'little')&sum(1<<k for k in FACE_CHANNELS);self.assertIn(face,(0,8))
        c.end(True)
    def test_pause_drops_face_and_retains_head_without_ns(self):
        c=self.make();self.start(c);c.begin_face_trial(2,1500,True,False,True);c.tick(.05);c.pause();c.tick(.05)
        self.assertEqual(c.last_state['active_mask'],MASK);self.assertEqual(c.last_trial['status'],'aborted')
        self.assertFalse(any(p[:2]==b'NS' for p in Board.instances[-1].packets));c.end(True)
    def test_limits_require_actual_loaded_neutral_observation(self):
        c=self.make();self.start(c)
        with self.assertRaises(ValueError):c.begin_face_trial(2,1100,True,True)
        c.begin_face_trial(2,1500,True,False,True);c.tick(.05);self.clock[0]=.21;c.tick(.05)
        with self.assertRaises(ValueError):c.record_face_observation(3,'neutral')
        c.record_face_observation(2,'neutral');self.assertTrue(c.records[0]['mounted_neutral_verified']);self.assertFalse(c.records[0]['full_range_verified'])
        c.begin_face_trial(2,1450,True);c.tick(.05);self.clock[0]=4;c.tick(.05);c.record_face_observation(2,'min')
        self.assertEqual(c.records[0]['observed_min_us'],1450);c.end(True)
    def test_decoupled_neutral_does_not_verify_mounted_neutral(self):
        c=self.make();self.start(c);c.begin_face_trial(2,1500,True,True);c.tick(.05);self.clock[0]=1;c.tick(.05);c.record_face_observation(2,'neutral')
        self.assertTrue(c.records[0]['unloaded_center_verified']);self.assertFalse(c.records[0]['mounted_neutral_verified'])
        with self.assertRaises(ValueError):c.begin_face_trial(2,1510,True)
        c.end(True)
    def test_tracking_rejected_during_active_face_trial(self):
        c=self.make();self.start(c);c.begin_face_trial(2,1500,True,False,True)
        with self.assertRaises(ValueError):c.set_follow('eyes')
        c.stop_face();c.tick(.05);self.assertEqual(c.last_state['active_mask'],MASK);c.end(True)
    def test_plan_rejects_duplicate_missing_and_overwide_windows(self):
        for change in ('duplicate','missing','wide'):
            p=plan()
            if change=='duplicate':p[1]['channel']=2
            if change=='missing':p.pop()
            if change=='wide':p[0]['trial_min_us']=600
            with self.assertRaises(ValueError):validate_plan(p)
    def test_plain_head_after_commission_never_enables_face(self):
        c=self.make();self.start(c);b=Board.instances[-1];c.end(True)
        # Reuse a board retaining its facial configuration, as real NS does.
        h=HeadControl(profile(),client_factory=lambda **_:b,lock_factory=lambda _:Lock());h._guard=lambda:None
        with patch('eye_follow_panel.verified_command',return_value=[]):h.start()
        h.tick(.05);self.assertEqual(h.last_state['active_mask'],MASK);h.end(True)
    def test_session_one_worker_continues_during_ui_block(self):
        s=FaceSession(dict(profile(),face_channels=plan()),client_factory=Board,lock_factory=lambda _:Lock())
        try:
            with patch('eye_follow_panel.verified_command',return_value=[]):s.start()
            s.face_trial(2,1500,True,False,True);time.sleep(.4)
            self.assertEqual(s.extra['face_last_trial']['status'],'completed');self.assertIsNone(s.extra['face_trial']);self.assertEqual(s.last_state['active_mask'],MASK)
            s.end(True)
        finally:
            if s.mode!='idle':s.end(True)
            s.close()
if __name__=='__main__':unittest.main(verbosity=2)
