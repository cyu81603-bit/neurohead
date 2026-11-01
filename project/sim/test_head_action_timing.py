"""Faster gestures must retain their rate, acceleration and jerk envelopes."""
import math,unittest
import test_left_lower_lid_guard as guard
from test_head_control import profile
from action_library import HeadGesture,travel_fraction


class TimingTests(unittest.TestCase):
    def test_reference_actions_are_faster_with_identical_endpoints(self):
        p=profile();p['neck_tracking_rate_us_per_s']=[50,35]
        baseline=[1500,1500,1500,1270,1500]
        expected={'eyes_up':(3.45,1,1800),'head_up':(3.7,3,1170),'shake_head':(5.7,2,1400)}
        for name,(deadline,axis,target) in expected.items():
            g=HeadGesture(name,baseline,p,0)
            self.assertLess(g.end,deadline)
            self.assertEqual(g.segments[0][4][axis],target)
            self.assertEqual(g.sample(g.end),{i:baseline[i] for i in g.indices})

    def test_float_curve_speed_acceleration_and_jerk_remain_bounded(self):
        for distance,speed,ramp,accel_cap,jerk_cap in (
                (300,300,.4,1200,12000),(100,35,.5,35*10/3,35*80/3),
                (100,100,.4,500,5000),(200,120,.4,500,5000),
                (200,50,.5,50*3.25,50*25),(1,50,.5,50*3.25,50*25)):
            duration=max(2*ramp,distance/speed+ramp);dt=.002
            xs=[distance*travel_fraction(i*dt,duration,ramp) for i in range(-4,math.ceil(duration/dt)+5)]
            derivatives=xs
            for cap in (speed,accel_cap,jerk_cap):
                derivatives=[(b-a)/dt for a,b in zip(derivatives,derivatives[1:])]
                self.assertLessEqual(max(map(abs,derivatives)),cap+1.)
            self.assertEqual(travel_fraction(-1,duration,ramp),0.)
            self.assertEqual(travel_fraction(duration+1,duration,ramp),1.)

    def test_zero_travel_return_has_no_division_error_and_still_confirms(self):
        p=profile();p['neck_tracking_rate_us_per_s']=[50,35]
        baseline=[1500,1500,1400,1270,1500]
        g=HeadGesture('shake_head',baseline,p,0)
        self.assertEqual(g.segments[0][1],0)
        for tick in range(math.ceil(g.end/.05)+1):
            now=tick*.05;actual=list(baseline)
            for i,u in g.sample(now).items():actual[i]=u
            g.observe(now,actual,actual)
        self.assertFalse(g.completion_error())


if __name__=='__main__':unittest.main()
