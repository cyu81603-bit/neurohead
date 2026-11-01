"""Integrated fixed jaw and gaze isolation, fake hardware only."""
import copy,json,struct,sys,unittest
from pathlib import Path
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'src/pc'),str(ROOT/'sim')]
from jaw_motion import FixedPointJaw,fixed_point_plan
from lifelike_behavior import ExpressionEngine
from lifelike_control import LifelikeControl
from test_head_control import profile,Lock
from test_face_commission import Board
from head_control import CHANNELS,MASK

def live_config():
    return json.loads((ROOT/'config/lifelike_v6.json').read_text(encoding='utf-8'))

class JawFixedTests(unittest.TestCase):
    def core(self,cfg=None):
        self.now=[0.];Board.instances=[];Board.fail=False
        c=LifelikeControl(dict(profile(),lifelike=cfg or live_config()),clock=lambda:self.now[0],client_factory=Board,lock_factory=lambda _:Lock())
        c._guard=lambda:None
        with patch('eye_follow_panel.verified_command',return_value=[]):c.start()
        self.addCleanup(lambda:c.end(True) if c.mode!='idle' else None)
        return c

    def test_operator_verified_live_endpoints_and_manual_range(self):
        cfg=live_config();j=cfg['jaw_setup'];plan=fixed_point_plan(j)
        self.assertEqual((plan['closed_us'],plan['open_us'],plan['frame_step_us']),(1300,1200,100))
        self.assertTrue(j['manual_full_range'])
        self.assertFalse(cfg['automatic_blink'])

    def test_fixed_hardware_step_and_other_channel_config_preserved(self):
        cfg=live_config();legacy=copy.deepcopy(cfg);legacy['jaw_setup'].pop('drive_mode')
        a=self.core(legacy);old=dict(a.client.config_rows);a.end(True)
        b=self.core(cfg);new=b.client.config_rows
        self.assertEqual(struct.unpack_from('<HHHH',new[21],10),(600,2400,1300,100))
        for ch in old:
            if ch!=21:self.assertEqual(old[ch],new[ch])

    def test_constant_voice_repeats_endpoints_without_intermediate_pwm(self):
        e=ExpressionEngine(live_config());e.enable(0)
        values=[]
        for i in range(120):
            t=i*.05;e.speech.external(1.,t,'tts');values.append(e.step(t)[21])
        self.assertEqual(set(values),{1200,1300})
        self.assertGreaterEqual(sum(a!=b for a,b in zip(values,values[1:])),6)

    def test_hysteresis_does_not_chatter_in_noise_band(self):
        j=FixedPointJaw(fixed_point_plan(live_config()['jaw_setup']))
        for i in range(100):self.assertEqual(j.step(i*.02,.25+(i%2)*.03,True),1300)
        self.assertEqual(j.step(2.,1.,True),1200)
        self.assertEqual(j.step(2.05,.25,True),1200)
        self.assertEqual(j.step(2.46,.25,True),1300)
        self.assertEqual(j.step(2.5,1.,True),1300)

    def test_speech_end_and_stale_energy_close_immediately(self):
        e=ExpressionEngine(live_config());e.enable(0);e.speech.external(1.,.6,'tts')
        self.assertEqual(e.step(.6)[21],1200)
        e.speech.stop();self.assertEqual(e.step(.61)[21],1300)
        e.speech.external(1.,1.,'tts');self.assertEqual(e.step(1.)[21],1200)
        self.assertEqual(e.step(1.36)[21],1300)

    def test_normal_stop_sends_closed_point_before_face_mask_removal(self):
        cfg=live_config();cfg['poses']=[p for p in cfg['poses'] if p['channel']==21]
        e=ExpressionEngine(cfg);e.enable(0);e.speech.external(1.,.6,'tts');e.step(.6)
        e.stop(.61)
        self.assertEqual(e.step(.62),{21:1300})
        self.assertEqual(e.step(3.5),{21:1300})
        self.assertEqual(e.step(3.62),{})

    def test_immediate_stop_removes_all_facial_output(self):
        e=ExpressionEngine(live_config());e.enable(0);e.speech.external(1.,.6,'tts');e.step(.6)
        e.stop(.61,True);self.assertEqual(e.step(.62),{})

    def test_jaw_and_other_expressions_preserve_all_head_fields(self):
        c=self.core();c.enable_life(True);c.tracking='coordinated';values=[1530,1470,1510,1260,1510];jaw=[]
        for i in range(80):
            self.now[0]=i*.05;c.life_event(dict(type='speech.energy',id='tts',energy=1.))
            state=c._send_motion(values);packet=c.client.packets[-1];p=struct.unpack_from('<22H',packet,12)
            self.assertEqual([p[ch] for ch in CHANNELS],values)
            self.assertEqual(state['active_mask']&MASK,MASK)
            jaw.append(p[21])
        self.assertEqual(set(jaw),{1200,1300})
        with patch('head_control.HeadControl._visual_tick') as v:
            c._visual_tick();v.assert_called_once()

    def test_revoked_fixed_calibration_keeps_gaze_available(self):
        cfg=live_config();cfg['jaw_setup']['fixed_point_verified']=False
        c=self.core(cfg);c.enable_life(True);self.now[0]=.7
        self.assertNotIn(21,c.engine.poses)
        self.assertFalse(c._send_motion([1500,1500,1500,1270,1500])['active_mask']&(1<<21))

    def test_changed_endpoint_or_bad_timing_blocks_fixed_jaw(self):
        for key,value in [('observed_open_us',1250),('fixed_point_timing',{'min_closed_s':-1}),('fixed_point_calibration',None)]:
            cfg=live_config();cfg['jaw_setup'][key]=value
            e=ExpressionEngine(cfg);self.assertNotIn(21,e.poses);self.assertIn(21,e.blocked)

    def test_manual_new_endpoint_cannot_reuse_old_fixed_point_approval(self):
        c=self.core();c.preview_jaw_manual(1250,True)
        for _ in range(130):self.now[0]+=.05;c._send_motion([1500,1500,1500,1270,1500])
        self.assertIsNone(c.preview)
        cfg=c.record_jaw_open();self.assertFalse(cfg['jaw_setup']['fixed_point_verified'])
        with self.assertRaises(ValueError):c.use_jaw_for_speech(True)

    def test_audio_timeline_returns_closed_at_end(self):
        e=ExpressionEngine(live_config());e.enable(0);e.step(.6);e.speech.timeline([1.]*150,.02,.6)
        values=[e.step(.6+i*.02)[21] for i in range(200)]
        self.assertEqual(set(values),{1200,1300});self.assertEqual(values[-1],1300)

if __name__=='__main__':unittest.main()
