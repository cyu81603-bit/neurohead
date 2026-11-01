"""Actual mixed packets with fake board; no motion, camera or microphone IO."""
import copy,struct,unittest
from unittest.mock import patch
import test_left_lower_lid_guard as guard
from lifelike_behavior import ExpressionEngine
from expression_presets import PresetLayer,wink_signature
from head_control import CHANNELS,MASK
current=guard.current


class PresetTests(unittest.TestCase):
    def engine(self):
        cfg=current();cfg['wink_right_approval']={'verified':False}
        e=ExpressionEngine(cfg,0,1);e.enable(0);e.step(.6)
        e.next_stretch=e.next_blink=100
        return e

    def test_smile_uses_bilateral_lips_cheeks_and_sad_inner_brows(self):
        for name in ('smile','sad'):
            e=self.engine();e.preset.trigger(name,.6,3,.8,e.poses)
            for i in range(1,86):out=e.step(.6+i*.02)
            if name=='smile':
                self.assertGreater(out[10],1600);self.assertLess(out[12],1400)
                self.assertGreater(out[15],1650);self.assertGreater(out[17],1650)
                # Unapproved right upper cheek prevents an asymmetric upper pair.
                self.assertEqual(out[14],1500);self.assertNotIn(16,out)
            else:
                self.assertGreater(out[2],1700);self.assertLess(out[4],1300)
                self.assertEqual(out[3],1500);self.assertEqual(out[5],1500)
            self.assertEqual(out[21],1300)
            self.assertNotIn(7,out)
            for i in range(86,220):out=e.step(.6+i*.02)
            self.assertEqual(e.preset.name,'neutral')
            for ch in (2,3,4,5,10,11,12,13,15,17):self.assertAlmostEqual(out[ch],1500,delta=1)

    def test_crossfade_no_jump_when_replaced_and_input_validation(self):
        e=self.engine();layer=e.preset;layer.trigger('smile',1,3,1,e.poses)
        before=layer.sample(1.5);layer.trigger('sad',1.5,3,.8,e.poses)
        self.assertEqual(before,layer.sample(1.5))
        for duration,intensity in ((float('nan'),.8),(3,float('inf')),(True,.5),(3,-1),(30,.8)):
            with self.assertRaises(ValueError):layer.trigger('smile',2,duration,intensity,e.poses)
        with self.assertRaises(ValueError):layer.trigger('raw_pwm',2,3,1,e.poses)

    def test_unapproved_pairs_cannot_be_requested(self):
        layer=PresetLayer()
        with self.assertRaises(ValueError):layer.trigger('smile',0,3,1,{2:{}})

    def test_speech_keeps_fixed_jaw_and_lip_articulation_under_sad(self):
        e=self.engine();e.preset.trigger('sad',.6,3,.8,e.poses)
        e.speech.timeline([.95]*40+[0.]*30+[.95]*30+[0.]*90,.02,.6)
        outputs=[e.step(.6+i*.02) for i in range(200)]
        self.assertEqual({v[21] for v in outputs},{1200,1300})
        self.assertGreater(max(v[10] for v in outputs),1700)
        self.assertEqual(outputs[-1][21],1300)

    def test_right_wink_is_independent_and_does_not_hold_visuals(self):
        e=self.engine()
        with self.assertRaisesRegex(ValueError,'确认'):e.wink_once(.7)
        e.wink_once(.7,trial=True)
        with self.assertRaises(ValueError):e.wink_once(.71,trial=True)
        self.assertFalse(e.blink_once(.71))
        outputs=[e.step(.7+i*.02) for i in range(65)]
        self.assertGreater(max(v[8] for v in outputs),1750)
        self.assertEqual(outputs[-1][8],1500)
        self.assertTrue(all(6 not in v and v[9]==1500 and 7 not in v for v in outputs))
        self.assertFalse(e.vision_hold(.8))
        e.config['wink_right_approval']={'verified':True,'tracking_clear':True,'pose':wink_signature(e.poses[8])}
        e.wink_once(3)
        e.stop(3.2,True);self.assertEqual(e.step(3.3),{})
        e.config['wink_right_approval']['tracking_clear']=False;e.enable(4);e.step(4.6)
        with self.assertRaises(ValueError):e.wink_once(5)
    def test_left_approval_never_authorizes_right_and_disabled_right_is_blocked(self):
        e=self.engine();e.config['wink_right_approval']={'verified':False}
        e.config['wink_left_approval']={'verified':True,'tracking_clear':True,'pose':wink_signature(next(p for p in e.config['poses'] if p['channel']==6))}
        with self.assertRaises(ValueError):e.wink_once(.7)
        e.config['wink_right_approval']={'verified':True,'tracking_clear':True,'pose':wink_signature(next(p for p in e.config['poses'] if p['channel']==6))}
        with self.assertRaises(ValueError):e.wink_once(.7)
        e.poses.pop(8)
        with self.assertRaises(ValueError):e.wink_once(.7,trial=True)


class PacketTests(unittest.TestCase):
    make=guard.GuardTests.make

    def test_all_presets_keep_tracking_fields_and_guard_in_real_packets(self):
        c=self.make();self.addCleanup(c.end,True);c.enable_life(True)
        c.tracking='coordinated';head=[1510,1490,1520,1260,1510]
        self.clock[0]=.6;c._send_motion(head)
        c.engine.config['wink_right_approval']={'verified':True,'tracking_clear':True,'pose':wink_signature(c.engine.poses[8])}
        for name in ('smile','sad','wink','neutral','happy','笑','难过'):
            c.life_event(dict(type='expression',name=name,duration_s=2))
            for _ in range(55):
                self.clock[0]+=.05;c._send_motion(head)
                pkt=c.client.packets[-1];mask=int.from_bytes(pkt[8:12],'little')
                self.assertFalse(mask&(1<<7));self.assertEqual(mask&MASK,MASK)
                pulses=struct.unpack_from('<22H',pkt,12)
                self.assertEqual([pulses[ch] for ch in CHANNELS],head)
                self.assertEqual(c.tracking,'coordinated')
                self.assertTrue(all(c.pose_map[ch]['min_us']<=pulses[ch]<=c.pose_map[ch]['max_us'] for ch in c.engine.poses))
            with patch('head_control.HeadControl._visual_tick') as visual:
                c._visual_tick();visual.assert_called_once()

    def test_wink_requires_completed_output_and_operator_confirmation(self):
        c=self.make();self.addCleanup(c.end,True);c.enable_life(True)
        self.clock[0]=.6;c._send_motion(c.reference)
        with self.assertRaises(ValueError):c.approve_right_wink(True)
        with self.assertRaises(ValueError):c.trial_right_wink(False)
        c.trial_right_wink(True)
        with self.assertRaises(ValueError):c.approve_right_wink(True)
        for i in range(1,35):self.clock[0]=.6+i*.05;c._send_motion(c.reference)
        with self.assertRaises(ValueError):c.approve_right_wink(False)
        cfg=c.approve_right_wink(True);self.assertTrue(cfg['wink_right_approval']['verified']);self.assertTrue(cfg['wink_right_approval']['tracking_clear'])
        c.life_event({'type':'expression','name':'wink'})
        c.engine.wink.event=None;c.engine.poses[8]['action_us']=1100
        with self.assertRaises(ValueError):c.life_event({'type':'expression','name':'wink'})
    def test_right_wink_packets_never_output_left_upper(self):
        c=self.make();self.addCleanup(c.end,True);c.enable_life(True)
        self.clock[0]=.6;c._send_motion(c.reference);c.trial_right_wink(True)
        right=[]
        for i in range(1,35):
            self.clock[0]=.6+i*.025;c._send_motion(c.reference)
            packet=c.client.packets[-1];pulses=struct.unpack_from('<22H',packet,12)
            self.assertEqual(pulses[6],0)
            self.assertFalse(int.from_bytes(packet[8:12],'little')&(1<<6))
            self.assertFalse(int.from_bytes(packet[8:12],'little')&(1<<7))
            self.assertEqual(pulses[9],c.pose_map[9]['neutral_us'])
            self.assertEqual([pulses[ch] for ch in CHANNELS],list(c.reference))
            right.append(pulses[8])
        self.assertGreater(max(right),1750);self.assertEqual(right[-1],1500)
        for name in ('wink_left','左眼wink'):
            with self.assertRaises(ValueError):c.life_event({'type':'expression','name':name})

    def test_cancelled_trial_never_approves_and_raw_pwm_still_rejected(self):
        c=self.make();self.addCleanup(c.end,True);c.enable_life(True)
        self.clock[0]=.6;c._send_motion(c.reference);c.trial_right_wink(True)
        self.clock[0]=.7;c._send_motion(c.reference)
        c.life_event({'type':'expression','name':'neutral'});self.clock[0]=.75;c._send_motion(c.reference)
        self.assertEqual(c.last_wink_trial['status'],'aborted')
        with self.assertRaises(ValueError):c.approve_right_wink(True)
        with self.assertRaises(ValueError):c.life_event({'type':'set_pwm','channel':7,'us':1100})


if __name__=='__main__':unittest.main()
