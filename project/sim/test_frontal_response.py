import copy, math, sys, unittest
from pathlib import Path
from types import SimpleNamespace as NS
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'src/pc'),str(ROOT/'sim')]
from frontal_gaze import FrontalCoordinator
from head_motion import MotionBank
from head_follow_panel import Panel
from test_head_control import profile

RESPONSE=dict(engage_delay_s=.05,engage_ramp_s=.20,eye_offset_tau_s=.10,image_error_tau_s=.08,neck_rate_tau_s=.12)
CAL=dict(valid=True,reference_us=[1500,1270,1500],inverse=[[500,0],[0,240]],automatic_yaw_limit_us=100,automatic_pitch_limit_us=100)

class ResponseTests(unittest.TestCase):
    def simulate(self,responsive):
        p=dict(profile(),neck_tracking_gain=.65,neck_tracking_rate_us_per_s=[50,35] if responsive else [40,30])
        if responsive:p['frontal_response']=RESPONSE
        v=[1500,1500,1500,1270,1500];c=FrontalCoordinator(p,v)
        bank=MotionBank(v,[1000,2000],[1500,1270,1500],p['neck_tracking_rate_us_per_s'])
        rows=[]
        for i in range(120):
            target=c.update(dict(frame_id=i,frame_time=i*.05,target=[.45,.25]),v,CAL)
            v=[round(x) for x in bank.step(target,.05,True)];rows.append(v)
            self.assertTrue(1400<=v[2]<=1600 and 1170<=v[3]<=1370 and 1400<=v[4]<=1600)
        return rows,c

    def test_response_begins_earlier_without_expanding_travel(self):
        old,_=self.simulate(False);new,_=self.simulate(True)
        onset=lambda rows:next(i for i,v in enumerate(rows) if abs(v[2]-1500)>=3)
        self.assertLess(onset(new),onset(old))
        self.assertGreater(abs(new[19][2]-1500),abs(old[19][2]-1500))

    def test_no_face_stops_neck_velocity(self):
        rows,c=self.simulate(True);v=rows[-1]
        out=c.update(dict(frame_id=120,frame_time=6.,target=None),v,CAL)
        self.assertEqual(c.neck_rates,[0.,0.]);self.assertEqual(out[2:],rows[-1][2:])

    def test_duplicate_frame_does_not_advance(self):
        _,c=self.simulate(True)
        self.assertIsNone(c.update(dict(frame_id=119,frame_time=5.95,target=[.5,.5]),[1500]*5,CAL))

    def test_invalid_timing_rejected(self):
        for value in (float('nan'),0,-1,2):
            p=dict(profile(),frontal_response=dict(engage_ramp_s=value))
            with self.assertRaises(ValueError):FrontalCoordinator(p,[1500,1500,1500,1270,1500])

    def test_manual_slider_callback_cannot_cancel_coordination(self):
        messages=[];synced=[]
        fake=NS(syncing=False,control=NS(mode='running',extra=dict(tracking='coordinated'),desired=[1500,1500,1500,1270,1500]),sync=lambda values:synced.append(values),status=NS(set=messages.append))
        Panel.changed(fake,2)
        self.assertEqual(fake.control.extra['tracking'],'coordinated')
        self.assertEqual(synced,[fake.control.desired]);self.assertTrue(messages)

if __name__=='__main__':unittest.main()
