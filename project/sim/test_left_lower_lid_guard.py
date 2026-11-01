import copy,json,sys,unittest,struct
from pathlib import Path
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'src/pc'),str(ROOT/'sim')]
from lifelike_behavior import ExpressionEngine
from lifelike_control import LifelikeControl
from test_head_control import profile,Lock
from test_face_commission import Board
from head_control import CHANNELS,MASK

def current():return json.loads((ROOT/'config/lifelike_v6.json').read_text(encoding='utf-8'))

class GuardTests(unittest.TestCase):
    def make(self):
        self.clock=[0.];Board.instances=[];Board.fail=False
        c=LifelikeControl(dict(profile(),lifelike=current()),clock=lambda:self.clock[0],client_factory=Board,lock_factory=lambda _:Lock())
        c._guard=lambda:None
        with patch('eye_follow_panel.verified_command',return_value=[]):c.start()
        return c

    def test_inhibited_lid_absent_from_warming_expression_blink_and_return(self):
        cfg=current();cfg.update(automatic_blink=True,blink_pair_verified=True,camera_clear_blink_verified=True,blink_lower_lids=True)
        e=ExpressionEngine(cfg,0,1);e.enable(0)
        self.assertNotIn(7,e.poses);self.assertIn(7,e.blocked)
        for i in range(200):
            t=i*.02
            if i==30:e.mood='happy';e.mood_end=2;e.blink_once(t)
            if i==40:e.speech.external(.9,t)
            if i==100:e.stop(t)
            self.assertNotIn(7,e.step(t,.8))

    def test_actual_motion_masks_exclude_lid_and_keep_head_targets(self):
        c=self.make();c.enable_life(True);head=[1510,1490,1520,1260,1510]
        for i in range(50):
            self.clock[0]=i*.05;c._send_motion(head)
            pkt=c.client.packets[-1];mask=int.from_bytes(pkt[8:12],'little')
            self.assertFalse(mask&(1<<7));self.assertEqual(mask&MASK,MASK)
            pulses=struct.unpack_from('<22H',pkt,12)
            self.assertEqual([pulses[ch] for ch in CHANNELS],head)
        c.end(True)

    def test_explicit_manual_preview_remains_available_but_never_approves_auto(self):
        c=self.make()
        with self.assertRaises(ValueError):c.preview_joint(7,False)
        c.preview_joint(7,True);self.clock[0]=.05;c._send_motion(list(c.reference))
        mask=int.from_bytes(c.client.packets[-1][8:12],'little');self.assertTrue(mask&(1<<7))
        c.preview=None;c.last_preview=dict(channel=7,status='completed')
        with self.assertRaisesRegex(ValueError,'屏蔽'):c.approve_pose(7)
        c.end(True)

    def test_editing_pose_cannot_erase_existing_inhibit_flag(self):
        c=self.make();p=copy.deepcopy(c.pose_map[7]);p.pop('automatic_inhibited');p.pop('automatic_inhibited_reason')
        cfg=c.update_pose(p);edited=next(p for p in cfg['poses'] if p['channel']==7)
        self.assertTrue(edited['automatic_inhibited']);self.assertFalse(edited['enabled']);c.end(True)

if __name__=='__main__':unittest.main()
