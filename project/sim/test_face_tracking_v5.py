"""Tracking/expression isolation and articulation; fake board only."""
import copy,sys,unittest,struct
from pathlib import Path
from unittest.mock import patch
import numpy as np
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'src/pc'),str(ROOT/'sim')]
from test_lifelike import config
from test_head_control import profile,Lock
from test_face_commission import Board
from lifelike_control import LifelikeControl
from lifelike_behavior import ExpressionEngine
from articulation import speech_envelope
from head_control import CHANNELS,MASK


class IsolationTests(unittest.TestCase):
    def control(self):
        cfg=config(tuple(range(2,18)));cfg.update(expression_style='active',speech_articulation='pcm_gaps')
        self.clock=[0.];Board.instances=[];Board.fail=False
        c=LifelikeControl(dict(profile(),lifelike=cfg),clock=lambda:self.clock[0],client_factory=Board,lock_factory=lambda _:Lock());c._guard=lambda:None
        with patch('eye_follow_panel.verified_command',return_value=[]):c.start()
        return c
    def test_enable_expression_keeps_tracking_and_coordinator(self):
        c=self.control();c.tracking='coordinated';coordinator=object();c.coordinator=coordinator
        c.enable_life(True)
        self.assertEqual(c.tracking,'coordinated');self.assertIs(c.coordinator,coordinator)
        c.end(True)
    def test_single_face_preview_does_not_switch_gaze_to_manual(self):
        c=self.control();c.tracking='eyes';c.preview_joint(8,True)
        self.assertEqual(c.tracking,'eyes');c.end(True)
    def test_head_fields_are_identical_with_expression_and_speech(self):
        c=self.control();values=[1530,1470,1510,1260,1510]
        first=c._send_motion(values)
        c.enable_life(True);c.engine.blink_once(0)
        for i in range(1,40):
            self.clock[0]=i*.05;c.life_event(dict(type='speech.energy',energy=(i%4)/3,id='tts'))
            s=c._send_motion(values)
            packet=c.client.packets[-1];pulses=struct.unpack_from('<22H',packet,12)
            self.assertEqual([pulses[ch] for ch in CHANNELS],values)
            self.assertEqual(s['active_mask']&MASK,MASK)
            self.assertFalse(s['active_mask']&(1<<21))
        c.end(True)
    def test_fresh_vision_checked_during_entire_blink(self):
        c=self.control();c.enable_life(True);c.engine.blink_once(0);c.tracking='eyes'
        with patch('head_control.HeadControl._visual_tick') as tracking:
            for i in range(12):self.clock[0]=i*.05;c._visual_tick()
            self.assertEqual(tracking.call_count,12)
        c.end(True)


class BlinkTests(unittest.TestCase):
    def cfg(self):
        cfg=config((6,7,8,9));cfg.update(blink_pair_verified=True,camera_clear_blink_verified=True,tracking_blink_fraction=.2)
        for p in cfg['poses']:
            if p['channel'] in (6,7):p['action_us']=1900
            if p['channel'] in (8,9):p['action_us']=1100
        return cfg
    def test_opposite_pwm_polarities_have_same_normalized_closure(self):
        e=ExpressionEngine(self.cfg(),0,1);e.enable(0);e.step(.6);e.blink_once(.6)
        for i in range(30):
            out=e.step(.6+i*.02)
            self.assertAlmostEqual((out[6]-1500)/400,(out[8]-1500)/-400,places=2)
    def test_tracking_blink_is_shallow_and_bilateral(self):
        e=ExpressionEngine(self.cfg(),0,1);e.enable(0);e.step(.6);e.tracking_active=True;e.blink_once(.6)
        for i in range(30):
            out=e.step(.6+i*.02)
            self.assertTrue(1500<=out[6]<=1580);self.assertTrue(1420<=out[8]<=1500)
    def test_unverified_pair_or_camera_does_not_blink_automatically(self):
        cfg=self.cfg();cfg['blink_pair_verified']=False
        e=ExpressionEngine(cfg);self.assertFalse(e.blink_once(1))
        cfg['blink_pair_verified']=True;cfg['camera_clear_blink_verified']=False
        e=ExpressionEngine(cfg);e.tracking_active=True
        self.assertFalse(e.blink_once(1));self.assertTrue(e.blink_once(1,clearance_trial=True))
    def test_lower_lids_stay_open_during_blink_when_not_paired(self):
        cfg=self.cfg();cfg['blink_lower_lids']=False
        e=ExpressionEngine(cfg);e.enable(0);e.step(.6);e.blink_once(.6)
        values=[e.step(.6+i*.02) for i in range(30)]
        self.assertGreater(max(v[6] for v in values),1500)
        self.assertTrue(all(v[7]==1500 and v[9]==1500 for v in values))


class ArticulationTests(unittest.TestCase):
    def test_constant_voice_has_repeated_open_close_not_constant_open(self):
        pcm=np.full(16000,7000,dtype=np.int16)
        records=[dict(start_ms=0,end_ms=1000,norm_amplitude=1.)]
        frames,step=speech_envelope(pcm,16000,records)
        self.assertGreater(max(frames),.8)
        runs=sum(frames[i]==0 and frames[i-1]>0 for i in range(1,len(frames)))
        self.assertGreaterEqual(runs,2)
    def test_real_silence_stays_closed_regardless_of_character_metadata(self):
        frames,_=speech_envelope(np.zeros(16000,dtype=np.int16),16000,[dict(start_ms=0,end_ms=1000)])
        self.assertEqual(max(frames),0)
    def test_lips_return_close_and_brows_cheeks_share_speech_energy(self):
        cfg=config((2,4,10,11,12,13,14,15,16,17));cfg.update(expression_style='active',speech_articulation='pcm_gaps',automatic_blink=False)
        for p in cfg['poses']:
            if p['channel'] in range(10,14):p.update(max_rate_us_per_s=1800,action_us=1900)
        frames,step=speech_envelope(np.full(32000,6000,dtype=np.int16))
        e=ExpressionEngine(cfg,0,1);e.enable(0);e.step(.6);e.speech.timeline(frames+[0.]*100,step,.6)
        values=[e.step(.6+i*.02) for i in range(200)]
        self.assertGreater(max(v[10] for v in values),1550)
        self.assertAlmostEqual(values[-1][10],1500,delta=1)
        self.assertGreater(max(abs(v[2]-1500) for v in values),2)
        self.assertGreater(max(abs(v[14]-1500) for v in values),2)
        self.assertTrue(all(1500<=v[10]<=1900 for v in values))


if __name__=='__main__':unittest.main(verbosity=2)
