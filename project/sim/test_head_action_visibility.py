"""Boundary recovery, real packet ownership and PWM completion evidence."""
import math,struct,unittest
from unittest.mock import patch
import test_left_lower_lid_guard as guard
from action_library import HeadGesture
from test_head_control import profile
from head_control import CHANNELS


class VisibilityTests(unittest.TestCase):
    make=guard.GuardTests.make

    def run_action(self,c,name,baseline=None,exchange=None):
        if baseline is not None:
            c.output=list(baseline);c.command=list(map(float,baseline));c.desired=list(baseline)
            c.motion_bank.reset(baseline)
        c.profile['neck_tracking_rate_us_per_s']=[50,35]
        c.set_action_library(True,True)
        c.submit_actions(dict(type='action',request_id=name,actions=[name]))
        packets=[];phases=set()
        def tracking():c.desired=[1200,1000,1500,1270,1500]
        def restore(core,kind):core.tracking=kind
        c.tracking='coordinated';c.motion_style='natural'
        with patch.object(c,'_visual_tick',side_effect=tracking),patch('head_control.HeadControl.set_follow',restore):
            for _ in range(1000):
                self.clock[0]+=.05;c.tick(.05)
                if c.active_action:phases.add(c._action_snapshot()['progress']['phase'])
                packets.append(c.client.packets[-1])
                if not c.active_action and not c.action_queue:break
        return packets,phases

    def test_live_upper_boundary_rejects_instead_of_lowering_to_reference(self):
        p=profile();p['neck_tracking_rate_us_per_s']=[50,35]
        for left,right in ((1170,1600),(1171,1599),(1181,1589)):
            with self.assertRaisesRegex(ValueError,'上边界'):
                HeadGesture('head_up',[1577,1656,1600,left,right],p,0)
        baseline=[1500,1500,1500,1240,1530]
        g=HeadGesture('head_up',baseline,p,0)
        self.assertEqual(len(g.segments),2)
        self.assertEqual(g.segments[0][4][3:],[1170,1600])
        for tick in range(math.ceil(g.end/.05)+1):
            out=g.sample(tick*.05)
            self.assertLessEqual(out[3],baseline[3]);self.assertGreaterEqual(out[4],baseline[4])
            self.assertEqual(baseline[3]-out[3],out[4]-baseline[4])

    def test_eye_upper_boundary_has_visible_excursion_for_both_polarities(self):
        for reverse,at_limit,expected in ((False,2000,1800),(True,1000,1200)):
            p=profile();p['vertical_reverse']=reverse
            g=HeadGesture('eyes_up',[1500,at_limit,1500,1270,1500],p,0)
            self.assertEqual(g.segments[0][4][1],1500)
            self.assertEqual(g.segments[1][4][1],expected)
            self.assertEqual(g.segments[-1][4][1],at_limit)

    def test_all_three_emit_visible_packets_despite_conflicting_tracking_targets(self):
        for name in ('head_up','eyes_up','shake_head'):
            c=self.make();self.addCleanup(c.end,True)
            baseline=[1577,1656,1600,1270,1500] if name=='head_up' else [1577,1656,1600,1170,1600]
            packets,phases=self.run_action(c,name,baseline)
            self.assertEqual(c.action_last['status'],'completed',c.action_last)
            evidence=c.action_last['pwm_evidence']
            self.assertTrue(all(evidence['waypoints_confirmed']))
            self.assertGreaterEqual(len(phases),2)
            self.assertIn('实物',c.action_last['result_label'])
            values=[struct.unpack_from('<22H',p,12) for p in packets if p[:2]==b'NH']
            for p in packets:
                if p[:2]==b'NH':self.assertFalse(int.from_bytes(p[8:12],'little')&((1<<6)|(1<<7)))
            if name=='head_up':self.assertGreaterEqual(max(v[19] for v in values)-min(v[19] for v in values),95)
            elif name=='eyes_up':self.assertGreaterEqual(max(v[1] for v in values)-min(v[1] for v in values),295)
            else:self.assertGreaterEqual(max(v[18] for v in values)-min(v[18] for v in values),195)

    def test_ack_without_actual_pwm_excursion_can_never_report_completed(self):
        c=self.make();self.addCleanup(c.end,True)
        original=c.client.exchange
        def stuck(packet):
            state=original(packet)
            for ch,u in zip(CHANNELS,c.reference):state['output_us'][ch]=u
            return state
        with patch.object(c.client,'exchange',side_effect=stuck):self.run_action(c,'head_up')
        self.assertEqual(c.action_last['status'],'aborted')
        self.assertIn('未到位',c.action_last['reason'])
        self.assertEqual(c.mode,'paused')
        self.assertEqual(set(c.action_last['pwm_evidence']['output_delta_us'].values()),{0})
        self.assertFalse(c.action_enabled)

    def test_delayed_slew_telemetry_still_reaches_and_confirms_waypoints(self):
        c=self.make();self.addCleanup(c.end,True)
        original=c.client.exchange;actual=list(c.reference)
        def limited(packet):
            state=original(packet)
            if packet[:2]==b'NH':
                for i,ch in enumerate(CHANNELS):
                    target=state['output_us'][ch]
                    actual[i]+=max(-5,min(5,target-actual[i]))
                    state['output_us'][ch]=actual[i]
            return state
        with patch.object(c.client,'exchange',side_effect=limited):self.run_action(c,'shake_head')
        self.assertEqual(c.action_last['status'],'completed',c.action_last)
        self.assertTrue(all(c.action_last['pwm_evidence']['waypoints_confirmed']))
        self.assertTrue(c.action_history)


if __name__=='__main__':unittest.main()
