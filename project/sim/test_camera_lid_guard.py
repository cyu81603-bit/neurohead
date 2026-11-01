"""Camera lids must receive no automatic PWM, including startup neutral."""
import copy,struct,unittest
from unittest.mock import patch
import test_left_lower_lid_guard as guard
from lifelike_behavior import ExpressionEngine
from head_control import CHANNELS,MASK


class CameraLidTests(unittest.TestCase):
    make=guard.GuardTests.make

    def test_all_expression_phases_omit_both_camera_lids_even_if_blink_enabled(self):
        cfg=guard.current()
        cfg.update(automatic_blink=True,blink_pair_verified=True,camera_clear_blink_verified=True)
        e=ExpressionEngine(cfg,0,1);e.enable(0)
        for ch in (6,7):self.assertIn(ch,e.blocked);self.assertNotIn(ch,e.poses)
        for i in range(300):
            now=i*.02
            if i==30:e.preset.trigger('smile',now,2,.8,e.poses)
            if i==40:e.speech.timeline([.9]*30+[0.]*30,.02,now)
            if i==50:self.assertFalse(e.blink_once(now,direction_trial=True,clearance_trial=True))
            if i==80:e.wink_once(now,trial=True)
            if i==150:e.stop(now)
            out=e.step(now,.8)
            for ch in (6,7):self.assertNotIn(ch,out)

    def test_sender_blocks_stale_engine_output_and_preserves_tracking(self):
        c=self.make();self.addCleanup(c.end,True);c.enable_life(True)
        head=[1510,1490,1520,1260,1510]
        with patch.object(c.engine,'step',return_value={6:1500,7:1900,8:1500}):
            c._send_motion(head)
        packet=c.client.packets[-1];mask=int.from_bytes(packet[8:12],'little')
        pulses=struct.unpack_from('<22H',packet,12)
        self.assertEqual(mask&MASK,MASK)
        self.assertEqual([pulses[ch] for ch in CHANNELS],head)
        for ch in (6,7):self.assertFalse(mask&(1<<ch));self.assertEqual(pulses[ch],0)
        self.assertTrue(mask&(1<<8))

    def test_repeated_enable_and_return_never_send_startup_neutral_to_camera_lids(self):
        c=self.make();self.addCleanup(c.end,True)
        for _ in range(2):
            c.enable_life(True)
            for i in range(140):
                self.clock[0]+=.05
                if i==20:c.life_event(dict(type='expression',name='sad',duration_s=2))
                if i==60:c.disable_life()
                c._send_motion(c.reference)
                mask=int.from_bytes(c.client.packets[-1][8:12],'little')
                for ch in (6,7):self.assertFalse(mask&(1<<ch))

    def test_pose_edit_and_observation_cannot_reenable_camera_lid(self):
        c=self.make();self.addCleanup(c.end,True)
        pose=copy.deepcopy(c.pose_map[6]);pose.pop('automatic_inhibited');pose.pop('automatic_inhibited_reason')
        cfg=c.update_pose(pose);stored=next(p for p in cfg['poses'] if p['channel']==6)
        self.assertTrue(stored['automatic_inhibited']);self.assertFalse(stored['enabled'])
        c.last_preview=dict(channel=6,status='completed')
        with self.assertRaisesRegex(ValueError,'屏蔽'):c.approve_pose(6)
        with self.assertRaisesRegex(ValueError,'wink'):c.set_blink_policy(True,True)

    def test_camera_lid_moves_only_under_explicit_manual_preview(self):
        c=self.make();self.addCleanup(c.end,True)
        with self.assertRaises(ValueError):c.preview_joint(6,False)
        c.preview_joint(6,True);self.clock[0]=.05;c._send_motion(c.reference)
        self.assertTrue(int.from_bytes(c.client.packets[-1][8:12],'little')&(1<<6))


if __name__=='__main__':unittest.main()
