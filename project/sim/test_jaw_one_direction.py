"""Staged jaw commissioning with a fake board; never opens real hardware."""
import copy,json,sys,unittest
from pathlib import Path
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'src/pc'),str(ROOT/'sim')]
from test_head_control import profile,Lock
from test_face_commission import Board
from lifelike_control import LifelikeControl

class JawTests(unittest.TestCase):
    def setUp(self):
        self.now=[0.];Board.instances=[];Board.fail=False
        cfg=json.loads((ROOT/'config/lifelike_v6.json').read_text(encoding='utf-8'))
        # Historical negative-direction fixture; live calibration is independent.
        cfg['jaw_setup'].pop('drive_mode',None)
        cfg['jaw_setup'].update(closed_us=1500,observed_open_us=1475,candidate_min_us=1350,candidate_max_us=1650,operator_open_observed=True,automatic_committed=False)
        next(p for p in cfg['poses'] if p['channel']==21).update(neutral_us=1500,min_us=1475,max_us=1525,action_us=1475,max_rate_us_per_s=50,probe_only=True,range_confirmed=False,action_verified=False,enabled=False,neutral_verified=True)
        self.c=LifelikeControl(dict(profile(),lifelike=cfg),clock=lambda:self.now[0],client_factory=Board,lock_factory=lambda _:Lock())
        self.c._guard=lambda:None
        with patch('eye_follow_panel.verified_command',return_value=[]):self.c.start()
    def tearDown(self):self.c.end(True)
    def finish_probe(self):
        self.c.probe_jaw_open(True);target=self.c.preview['target_us'];duration=2*self.c.preview['half_s']
        pulses=[]
        for _ in range(round(duration/.05)+20):
            self.now[0]+=.05;state=self.c._send_motion([1500,1500,1500,1270,1500])
            if state['active_mask']&(1<<21):pulses.append(state['output_us'][21])
        self.assertIsNone(self.c.preview);return target,pulses
    def test_opening_is_staged_and_preserves_gaze(self):
        self.c.tracking='coordinated';coordinator=object();self.c.coordinator=coordinator
        self.assertNotIn(21,self.c.engine.poses)
        target,pulses=self.finish_probe()
        self.assertEqual(target,1450);self.assertTrue(pulses);self.assertGreaterEqual(min(pulses),1450);self.assertLessEqual(max(pulses),1500)
        self.assertEqual(self.c.tracking,'coordinated');self.assertIs(self.c.coordinator,coordinator)
        self.assertEqual(pulses[-1],1500)
        with self.assertRaises(ValueError):self.c.approve_pose(21)
    def test_record_requires_completed_motion_and_operator_action(self):
        with self.assertRaises(ValueError):self.c.record_jaw_open()
        self.finish_probe();self.assertEqual(self.c.life_config['jaw_setup']['observed_open_us'],1475)
        self.c.record_jaw_open();self.assertEqual(self.c.life_config['jaw_setup']['observed_open_us'],1450)
        with self.assertRaises(ValueError):self.c.record_jaw_open()
        self.c.probe_jaw_open(True);self.assertEqual(self.c.preview['target_us'],1425)
    def test_automatic_speech_uses_only_observed_interval(self):
        self.finish_probe();self.c.record_jaw_open();cfg=self.c.use_jaw_for_speech(True)
        self.assertTrue(cfg['jaw_setup']['automatic_committed']);p=self.c.engine.poses[21]
        self.assertEqual((p['min_us'],p['max_us'],p['neutral_us'],p['action_us']),(1450,1500,1500,1450))
        self.c.enable_life(True);values=[]
        for i in range(120):
            self.now[0]+=.05;self.c.life_event(dict(type='speech.energy',energy=float(i%20<10),id='test'))
            values.append(self.c._send_motion([1500,1500,1500,1270,1500])['output_us'][21])
        self.assertGreater(max(values)-min(values),25);self.assertTrue(all(1450<=v<=1500 for v in values))
    def test_positive_direction_is_not_available(self):
        for direction in (-1,1):
            with self.assertRaises(ValueError):self.c.probe_jaw(direction,True)
    def test_manual_target_bypasses_staged_and_automatic_bounds(self):
        self.c.tracking='eyes'
        for target in (1100,1900):
            self.c.preview_jaw_manual(target,True);self.assertEqual(self.c.preview['target_us'],target)
            duration=2*self.c.preview['half_s'];pulses=[]
            for _ in range(round(duration/.05)+20):
                self.now[0]+=.05;s=self.c._send_motion([1500,1500,1500,1270,1500])
                if s['active_mask']&(1<<21):pulses.append(s['output_us'][21])
            self.assertIsNone(self.c.preview);self.assertEqual(pulses[-1],1500)
            self.assertLessEqual(min(abs(p-target) for p in pulses),1)
            self.assertEqual(self.c.tracking,'eyes');self.assertNotIn(21,self.c.engine.poses)
        for target in (599,2401,1450.5):
            with self.assertRaises(ValueError):self.c.preview_jaw_manual(target,True)
    def test_manual_observation_can_record_a_larger_opening(self):
        self.c.preview_jaw_manual(1300,True)
        for _ in range(220):self.now[0]+=.05;self.c._send_motion([1500,1500,1500,1270,1500])
        self.assertEqual(self.c.life_config['jaw_setup']['observed_open_us'],1475)
        self.c.record_jaw_open();self.c.use_jaw_for_speech(True)
        self.assertEqual(self.c.engine.poses[21]['min_us'],1300)
    def test_no_confirmation_cannot_start_or_commit(self):
        with self.assertRaises(ValueError):self.c.probe_jaw_open(False)
        with self.assertRaises(ValueError):self.c.use_jaw_for_speech(False)
    def test_revoked_jaw_does_not_block_other_channels(self):
        self.c.end(True)
        self.c.life_config['jaw_setup'].update(operator_open_observed=False,automatic_committed=False)
        with patch('eye_follow_panel.verified_command',return_value=[]):self.c.start()
        self.assertNotIn(21,self.c.engine.poses)
        with self.assertRaises(ValueError):self.c.use_jaw_for_speech(True)
        self.c.enable_life(True);self.now[0]+=.05
        state=self.c._send_motion([1500,1500,1500,1270,1500])
        self.assertFalse(state['active_mask']&(1<<21))
        self.assertEqual(state['active_mask']&((1<<0)|(1<<1)|(1<<18)|(1<<19)|(1<<20)),(1<<0)|(1<<1)|(1<<18)|(1<<19)|(1<<20))
    def test_corrected_positive_direction_uses_1475_closed_1500_open(self):
        self.c.life_config['jaw_setup'].update(closed_us=1475,observed_open_us=1500)
        self.c.use_jaw_for_speech(True);p=self.c.engine.poses[21]
        self.assertEqual((p['neutral_us'],p['min_us'],p['max_us'],p['action_us']),(1475,1475,1500,1500))
        self.c.enable_life(True);values=[]
        for i in range(80):
            self.now[0]+=.05;self.c.life_event(dict(type='speech.energy',energy=float(i<40),id='test'))
            values.append(self.c._send_motion([1500,1500,1500,1270,1500])['output_us'][21])
        self.assertTrue(all(1475<=v<=1500 for v in values));self.assertGreater(max(values),1490);self.assertLess(values[-1],1480)
    def test_positive_direction_record_and_staging(self):
        self.c.life_config['jaw_setup'].update(closed_us=1475,observed_open_us=1500)
        self.c.preview_jaw_manual(1525,True)
        for _ in range(100):self.now[0]+=.05;self.c._send_motion([1500,1500,1500,1270,1500])
        self.c.record_jaw_open();self.c.use_jaw_for_speech(True)
        self.assertEqual(self.c.engine.poses[21]['action_us'],1525)
        self.c.probe_jaw_open(True);self.assertEqual(self.c.preview['target_us'],1550)
    def test_speech_cannot_commit_a_known_jammed_endpoint(self):
        self.c.life_config['jaw_setup'].update(closed_us=1475,observed_open_us=1900)
        with self.assertRaises(ValueError):self.c.use_jaw_for_speech(True)
        self.assertNotIn(21,self.c.engine.poses)

if __name__=='__main__':unittest.main()
