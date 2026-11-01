"""Real visual coordinator plus gestures; no hardware, camera or UI IO."""
import math,struct,unittest
from unittest.mock import patch
import test_left_lower_lid_guard as guard
from frontal_gaze import FrontalCoordinator
from action_library import head_up_room
from head_control import CHANNELS
from test_head_control import profile

CAL=dict(valid=True,reference_us=[1500,1270,1500],jacobian=[[.002,0],[0,1/240]],inverse=[[500,0],[0,240]],automatic_yaw_limit_us=100,automatic_pitch_limit_us=100)


class TrackingHeadroomTests(unittest.TestCase):
    make=guard.GuardTests.make

    def prepare(self,c,baseline=None):
        c.profile.update(neck_tracking_rate_us_per_s=[50,35],neck_tracking_gain=.65,prefer_frontal=True)
        if baseline:
            c.output=list(baseline);c.command=list(map(float,baseline));c.desired=list(baseline);c.motion_bank.reset(baseline)
        c.tracking='coordinated';c.motion_style='natural';c.calibration=dict(CAL)
        c.last_good_record=dict(success=True,camera_session='cam',calibration=dict(CAL))
        c.coordinator=c._frontal_coordinator(c.output)
        self.frames=0;self.target=[.35,-.4]
        def fresh():
            self.frames+=1
            target=[.12*math.sin(self.clock[0]*3),self.target[1]] if self.target is not None else None
            return dict(vision=dict(frame_id=self.frames,frame_time=self.clock[0],target=target,source_session_id='cam'))
        c._fresh_vision=fresh
        c.set_action_library(True,True)

    def step(self,c):self.clock[0]+=.05;c.tick(.05)

    def test_tracking_reserve_settles_without_snap_or_losing_frames(self):
        c=self.make();self.addCleanup(c.end,True)
        self.prepare(c,[1500,1500,1500,1170,1600])
        previous=list(c.output)
        for _ in range(160):
            self.step(c)
            self.assertEqual(c.tracking,'coordinated');self.assertEqual(c.mode,'running')
            for i in (3,4):self.assertLessEqual(abs(c.output[i]-previous[i]),3)
            previous=list(c.output)
        self.assertGreaterEqual(head_up_room(c.output,c.profile),78)
        self.assertGreater(self.frames,150)
        self.assertEqual(c.coordinator.head_up_reserve_us,80)

    def test_saturated_tracking_queues_then_lifts_while_visual_updates_continue(self):
        c=self.make();self.addCleanup(c.end,True)
        self.prepare(c,[1500,1500,1500,1170,1600])
        c.submit_actions(dict(type='action',request_id='tracking-up',actions=['head_up']))
        self.step(c);self.assertTrue(c.active_action['waiting_headroom'])
        gesture_started=None;out=[];unowned=[];before_frames=self.frames
        for _ in range(300):
            self.step(c)
            if c.active_action and c.active_action.get('gesture'):
                if gesture_started is None:gesture_started=list(c.active_action['gesture'].baseline)
                out.append(list(c.output));unowned.append(c.output[0])
                packet=c.client.packets[-1];mask=int.from_bytes(packet[8:12],'little')
                self.assertFalse(mask&((1<<6)|(1<<7)))
            if c.action_last and c.action_last.get('status') in ('completed','aborted','rejected') and not c.active_action:break
        self.assertEqual(c.action_last['status'],'completed',c.action_last)
        self.assertEqual(c.tracking,'coordinated');self.assertGreater(self.frames-before_frames,60)
        self.assertIsNotNone(gesture_started)
        self.assertGreaterEqual(gesture_started[3]-min(p[3] for p in out),75)
        self.assertGreater(len(set(unowned)),1)
        self.assertTrue(all(c.action_last['pwm_evidence']['waypoints_confirmed']))
        self.assertEqual(c.coordinator.head_up_reserve_us,80)

    def test_stale_visual_cancels_waiting_and_holds_without_blind_recenter(self):
        c=self.make();self.addCleanup(c.end,True)
        self.prepare(c,[1500,1500,1500,1170,1600])
        c.submit_actions(dict(type='action',request_id='stale',actions=['head_up']))
        self.step(c);held=list(c.output)
        def stale():raise ValueError('stale frame')
        c._fresh_vision=stale;self.step(c)
        self.assertEqual(c.tracking,'manual');self.assertIsNone(c.active_action)
        self.assertFalse(c.action_queue);self.assertEqual(c.output,held)
        self.assertEqual(c.action_last['reason'],'visual_hold')

    def test_disable_reserve_and_manual_mode_keep_old_full_range(self):
        c=self.make();self.addCleanup(c.end,True);self.prepare(c)
        c.set_action_library(False);self.assertEqual(c.coordinator.head_up_reserve_us,0)
        c.tracking='manual';c.output[3:]=[1170,1600];c.set_action_library(True,True)
        with self.assertRaisesRegex(ValueError,'上边界'):
            c.submit_actions(dict(type='action',request_id='manual-limit',actions=['head_up']))

    def test_cancel_wait_does_not_start_a_head_gesture_or_blind_return(self):
        c=self.make();self.addCleanup(c.end,True)
        self.prepare(c,[1500,1500,1500,1170,1600])
        c.submit_actions(dict(type='action',request_id='cancel',actions=['head_up','eyes_up']))
        self.step(c);self.assertTrue(c.active_action['waiting_headroom'])
        self.assertTrue(c.cancel_actions('cancel'))
        self.assertIsNone(c.active_action);self.assertFalse(c.action_queue)
        self.assertEqual(c.tracking,'coordinated')
        self.step(c);self.assertIsNone(c.active_action)

    def test_absent_face_does_not_start_headup_and_wait_expires(self):
        c=self.make();self.addCleanup(c.end,True)
        self.prepare(c,[1500,1500,1500,1170,1600]);self.target=None
        c.submit_actions(dict(type='action',request_id='no-face',actions=['head_up']))
        for _ in range(210):self.step(c)
        self.assertIsNone(c.active_action);self.assertFalse(c.action_queue)
        self.assertEqual(c.action_last['status'],'rejected')
        self.assertEqual(c.output[3:],[1170,1600]);self.assertEqual(c.tracking,'coordinated')

    def test_no_face_holds_during_reserve_transition_and_invalid_values_reject(self):
        p=profile();c=FrontalCoordinator(dict(p,head_up_reserve_us=80),[1500,1500,1500,1170,1600])
        out=c.update(dict(frame_id=1,frame_time=0.,target=None),[1500,1500,1500,1170,1600],CAL)
        self.assertEqual(out[3:],[1170,1600]);self.assertEqual(c.neck_rates,[0.,0.])
        for value in (True,101,-1,float('nan')):
            with self.assertRaises(ValueError):c.set_headroom(value)


if __name__=='__main__':unittest.main()
