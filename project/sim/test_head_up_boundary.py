"""An up request cannot start with a lowering preparation movement."""
import math,unittest
import test_left_lower_lid_guard as guard
from action_library import HeadGesture
from test_head_control import profile


class HeadUpBoundaryTests(unittest.TestCase):
    make=guard.GuardTests.make

    def test_reported_one_us_room_is_rejected_before_queue_or_pwm(self):
        c=self.make();self.addCleanup(c.end,True)
        c.output=[1500,1500,1500,1171,1599]
        c.set_action_library(True,True);before=len(c.client.packets)
        with self.assertRaisesRegex(ValueError,'上边界'):
            c.submit_actions(dict(type='action',request_id='one-us',actions=['head_up']))
        self.assertFalse(c.action_queue);self.assertIsNone(c.active_action)
        self.assertEqual(len(c.client.packets),before)

    def test_approach_and_return_never_overshoot_below_start_for_both_rod_polarities(self):
        for signs in ((-1,1),(1,-1)):
            p=profile();p['rod_up_pwm_signs']=list(signs)
            for offset in (-80,0,60,80):
                base=[1500,1500,1500,1270+signs[0]*offset,1500+signs[1]*offset]
                g=HeadGesture('head_up',base,p,0)
                self.assertEqual(g.labels,['抬头','回到动作前姿态'])
                for tick in range(math.ceil(g.end/.02)+1):
                    out=g.sample(tick*.02)
                    delta=[(out[i]-base[i])*sign for i,sign in zip((3,4),signs)]
                    self.assertEqual(delta[0],delta[1])
                    self.assertGreaterEqual(min(delta),0)
                self.assertEqual(g.sample(g.end),{3:base[3],4:base[4]})

    def test_tracking_polarities_profile_and_other_actions_are_unchanged(self):
        p=profile();before=dict(p);base=[1500,1500,1500,1270,1500]
        head=HeadGesture('head_up',base,p,0)
        self.assertEqual(p,before)
        self.assertEqual(head.segments[0][4][3:],[1170,1600])
        self.assertEqual(HeadGesture('eyes_up',base,p,0).segments[0][4][1],1800)
        yaw=HeadGesture('shake_head',base,p,0)
        self.assertEqual([segment[4][2] for segment in yaw.segments],[1400,1600,1500])


if __name__=='__main__':unittest.main()
