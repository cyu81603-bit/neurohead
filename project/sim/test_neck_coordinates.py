import sys,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src/pc'))
from neck_coordinates import *
class Tests(unittest.TestCase):
    p=dict(manual_neck_reference_us=[1500,1270,1500])
    def test_logical_center_is_calibrated_actual_pose(self):
        self.assertEqual(pose_to_pwm([1500]*3,self.p),[1500,1270,1500])
        self.assertEqual(pose_to_logical([1500,1270,1500],self.p),[1500]*3)
    def test_endpoints_and_monotonic_hardware_range_preserved(self):
        self.assertEqual(logical_to_pwm(1100,1,self.p),1100)
        self.assertEqual(logical_to_pwm(1900,1,self.p),1900)
        values=[logical_to_pwm(i,1,self.p) for i in range(1100,1901)]
        self.assertEqual(values,sorted(values));self.assertTrue(all(1100<=v<=1900 for v in values))
    def test_display_conversion_does_not_call_hardware(self):
        self.assertEqual(logical_to_pwm(1700,1,self.p),1585)
        self.assertEqual(pwm_to_logical(1585,1,self.p),1700)
    def test_outside_logical_range_rejected(self):
        with self.assertRaises(ValueError):logical_to_pwm(1000,1,self.p)
if __name__=='__main__':unittest.main(verbosity=2)