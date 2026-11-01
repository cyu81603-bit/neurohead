"""Fast eye gestures must survive board slew, preserve neck and obey bounds."""
import struct,unittest
from unittest.mock import patch
import test_left_lower_lid_guard as guard
from action_library import HeadGesture,eye_gesture_settings
from test_head_control import profile
from head_control import CHANNELS


class EyeSpeedTests(unittest.TestCase):
    make=guard.GuardTests.make

    def test_board_eye_step_matches_action_and_other_channels_keep_existing_steps(self):
        c=self.make();self.addCleanup(c.end,True)
        configs={p[8]:p for p in c.client.packets if p[:2]==b'NC'}
        self.assertEqual(int.from_bytes(configs[1][16:18],'little'),6)
        self.assertEqual(int.from_bytes(configs[18][16:18],'little'),3)
        for ch in (19,20):self.assertEqual(int.from_bytes(configs[ch][16:18],'little'),2)
        self.assertEqual(int.from_bytes(configs[0][16:18],'little'),4)
        self.assertEqual(c.motion_bank.neck_rates,[20,15])

    def test_eye_action_completes_with_board_20ms_slew_and_50ms_packets(self):
        c=self.make();self.addCleanup(c.end,True)
        original=c.client.exchange;actual=list(c.reference);min_eye=2000;max_eye=1000
        # Alternate two and three FPGA frames per 50ms control packet.
        frame=[0]
        def board_slew(packet):
            state=original(packet)
            if packet[:2]==b'NH':
                frame[0]+=1;count=2 if frame[0]%2 else 3
                for i,ch in enumerate(CHANNELS):
                    step=(6 if ch==1 else 4 if ch==0 else 2)*count
                    actual[i]+=max(-step,min(step,state['output_us'][ch]-actual[i]))
                    state['output_us'][ch]=actual[i]
            return state
        c.set_action_library(True,True)
        c.submit_actions(dict(type='action',request_id='fast-eye',actions=['eyes_up']))
        with patch.object(c.client,'exchange',side_effect=board_slew):
            for tick in range(100):
                self.clock[0]+=.05;c.tick(.05)
                min_eye=min(min_eye,c.output[1]);max_eye=max(max_eye,c.output[1])
                packet=c.client.packets[-1];pulses=struct.unpack_from('<22H',packet,12)
                self.assertEqual([pulses[ch] for ch in (19,20)],[1270,1500])
                self.assertFalse(int.from_bytes(packet[8:12],'little')&((1<<6)|(1<<7)))
                if not c.active_action and not c.action_queue:break
        self.assertEqual(c.action_last['status'],'completed',c.action_last)
        self.assertLess(self.clock[0],3.7)
        self.assertGreaterEqual(max_eye-min_eye,298)
        self.assertEqual(c.output[1],1500)

    def test_session_tuning_never_sends_motion_or_bypasses_observation_and_bounds(self):
        c=self.make();self.addCleanup(c.end,True);before=len(c.client.packets)
        with self.assertRaises(ValueError):c.set_eye_gesture(350,300,False)
        for delta,rate in ((401,300),(300,301),(True,300),(300,float('nan'))):
            with self.assertRaises(ValueError):c.set_eye_gesture(delta,rate,True)
        self.assertEqual(c.set_eye_gesture(350,250,True),dict(delta_us=350,rate_us_per_s=250))
        self.assertEqual(len(c.client.packets),before)
        g=HeadGesture('eyes_up',list(c.reference),c.profile,0)
        self.assertEqual(g.segments[0][4][1],1850);self.assertEqual(g.rates[1],250)
        c.set_action_library(True,True);c.submit_actions(dict(type='action',request_id='busy',actions=['eyes_up']))
        with self.assertRaises(ValueError):c.set_eye_gesture(300,300,True)

    def test_custom_eye_settings_do_not_change_head_and_yaw_trajectories(self):
        p=profile();base=[1500,1500,1500,1270,1500]
        changed=dict(p,eye_gesture_delta_us=400,eye_gesture_rate_us_per_s=300)
        for name in ('head_up','shake_head'):
            a=HeadGesture(name,base,p,0);b=HeadGesture(name,base,changed,0)
            self.assertEqual(a.segments,b.segments);self.assertEqual(a.rates,b.rates)
        for reverse in (False,True):
            g=HeadGesture('eyes_up',base,dict(changed,vertical_reverse=reverse),0)
            self.assertTrue(1000<=g.segments[0][4][1]<=2000)

    def test_head_gestures_complete_at_their_configured_fpga_slew(self):
        for name,deadline in (('head_up',4.),('shake_head',6.)):
            c=self.make();self.addCleanup(c.end,True)
            original=c.client.exchange;actual=list(c.reference);frame=[0]
            def limited(packet):
                state=original(packet)
                if packet[:2]==b'NH':
                    frame[0]+=1;count=2 if frame[0]%2 else 3
                    for i,ch in enumerate(CHANNELS):
                        step=(6 if ch==1 else 3 if ch==18 else 4 if ch==0 else 2)*count
                        actual[i]+=max(-step,min(step,state['output_us'][ch]-actual[i]))
                        state['output_us'][ch]=actual[i]
                return state
            c.set_action_library(True,True)
            c.submit_actions(dict(type='action',request_id=name,actions=[name]))
            with patch.object(c.client,'exchange',side_effect=limited):
                for _ in range(160):
                    self.clock[0]+=.05;c.tick(.05)
                    for ch,u in zip((18,19,20),(1500,1270,1500)):
                        self.assertLessEqual(abs(c.last_state['output_us'][ch]-u),100)
                    if not c.active_action and not c.action_queue:break
            self.assertEqual(c.action_last['status'],'completed',c.action_last)
            self.assertLess(self.clock[0],deadline)
            self.assertEqual(c.output,c.reference)

    def test_head_speed_tuning_has_no_io_and_cannot_change_tracking_limits(self):
        c=self.make();self.addCleanup(c.end,True);before=len(c.client.packets)
        for yaw,pitch in ((151,100),(120,101),(False,100),(120,float('inf'))):
            with self.assertRaises(ValueError):c.set_head_gesture_rates(yaw,pitch,True)
        with self.assertRaises(ValueError):c.set_head_gesture_rates(120,100,False)
        c.set_head_gesture_rates(100,80,True)
        self.assertEqual(len(c.client.packets),before)
        self.assertEqual(c.motion_bank.neck_rates,[20,15])
        for name in ('head_up','shake_head'):
            self.assertEqual(HeadGesture(name,list(c.reference),c.profile,0).rates[2:],[100,80,80])


if __name__=='__main__':unittest.main()
