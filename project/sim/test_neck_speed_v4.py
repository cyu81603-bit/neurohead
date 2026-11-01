import sys,copy,math,unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path[:0]=[str(ROOT/'src/pc'),str(ROOT/'sim')]
from head_motion import MotionBank,validate_neck_rates
from frontal_gaze import FrontalCoordinator
from test_head_control import profile
import test_lifelike as life_tests
class NeckSpeedTests(unittest.TestCase):
 def test_bank_accelerates_both_neck_axes_without_expanding_travel(self):
  def run(rates):
   b=MotionBank([1500,1500,1500,1270,1500],[1000,2000],[1500,1270,1500],rates)
   previous=[1500,1500,1500,1270,1500];after=None
   for i in range(200):
    v=b.step([1500,1500,1600,1170,1600],.05,True)
    for j,rate in zip((2,3,4),(rates[0],rates[1],rates[1])):self.assertLessEqual(abs(v[j]-previous[j]),rate*.05+1e-7)
    self.assertTrue(1400<=v[2]<=1600 and 1170<=v[3]<=1370 and 1400<=v[4]<=1600)
    if i==19:after=list(v)
    previous=v
   return [abs(after[j]-n) for j,n in zip((2,3,4),(1500,1270,1500))]
  slow,fast=run([20,15]),run([40,30])
  for a,b in zip(slow,fast):self.assertGreater(b,a*1.8)
 def test_frontal_feedback_uses_new_cap_despite_historical_rate_metadata(self):
  cal=dict(valid=True,reference_us=[1500,1270,1500],inverse=[[500,0],[0,200]],automatic_yaw_limit_us=100,automatic_pitch_limit_us=100,automatic_yaw_rate_us_per_s=20,automatic_pitch_rate_us_per_s=15)
  def run(fast):
   p=profile();v=[1500,1500,1500,1270,1500]
   if fast:p.update(neck_tracking_rate_us_per_s=[40,30],neck_tracking_gain=.65)
   c=FrontalCoordinator(p,v)
   for i in range(60):
    v=c.update(dict(frame_id=i,frame_time=i*.05,target=[.8,.7]),v,cal)
    self.assertTrue(1400<=v[2]<=1600 and 1170<=v[3]<=1370 and 1400<=v[4]<=1600)
   return abs(v[2]-1500)
  self.assertGreater(run(True),run(False)*1.5)
 def test_bad_caps_and_gains_rejected(self):
  for v in [[],[51,30],[40,36],[0,1],[float('nan'),1],['40',30]]:
   with self.assertRaises(ValueError):validate_neck_rates(v)
  with self.assertRaises(ValueError):FrontalCoordinator(dict(profile(),neck_tracking_gain=2),[1500,1500,1500,1270,1500])
 def test_runtime_speed_switch_retains_motion_state_and_range(self):
  helper=life_tests.ControlTests();c=helper.make((2,));old=c.motion_bank.axes[2].position
  c.set_neck_tracking_speed('faster');self.assertEqual(c.motion_bank.neck_rates,[40,30]);self.assertEqual(c.motion_bank.axes[2].position,old)
  self.assertEqual(c.profile['neck_tracking_gain'],.65)
  c.set_neck_tracking_speed('normal');self.assertEqual(c.motion_bank.neck_rates,[20,15]);c.end(True)
if __name__=='__main__':unittest.main()
