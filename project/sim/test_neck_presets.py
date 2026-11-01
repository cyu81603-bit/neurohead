import sys,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src/pc'))
from neck_presets import rod_up_signs,rod_preset,rod_shift
class Tests(unittest.TestCase):
    def profile(self,signs):return dict(rod_up_pwm_signs=signs,rod_directions_operator_verified=True)
    def test_mirrored_linkage_uses_same_pwm_for_opposite_rod_movement(self):
        p=self.profile([-1,1])
        self.assertEqual(rod_preset(1500,1,-1,p),[1500,1100,1100])
        self.assertEqual(rod_preset(1500,-1,1,p),[1500,1900,1900])
        self.assertEqual(rod_shift([1500]*3,50,p),[1500,1450,1550])
        self.assertEqual(rod_shift([1500]*3,-50,p),[1500,1550,1450])
    def test_parallel_polarities_remain_supported(self):
        p=self.profile([1,1])
        self.assertEqual(rod_preset(1600,1,-1,p),[1600,1900,1100])
        self.assertEqual(rod_shift([1600,1500,1500],50,p),[1600,1550,1550])
    def test_no_inversion_assumed_when_mapping_is_unverified(self):
        with self.assertRaises(ValueError):rod_preset(1500,1,-1,dict(rod_up_pwm_signs=[-1,1]))
        with self.assertRaises(ValueError):rod_up_signs(self.profile([0,1]))
    def test_bounds_and_yaw_are_preserved(self):
        p=self.profile([-1,1])
        self.assertEqual(rod_shift([1700,1100,1900],50,p),[1700,1100,1900])
    def test_offset_midpoint_uses_common_available_stroke(self):
        p=self.profile([-1,1]);p['manual_neck_reference_us']=[1500,1270,1500]
        self.assertEqual(rod_preset(1500,1,-1,p),[1500,1100,1330])
        self.assertEqual(rod_preset(1500,-1,1,p),[1500,1440,1670])
        self.assertEqual(rod_preset(1500,1,1,p),[1500,1100,1670])
        self.assertEqual(rod_preset(1500,-1,-1,p),[1500,1670,1100])
    def test_shared_step_stops_both_at_first_limit(self):
        p=self.profile([-1,1])
        self.assertEqual(rod_shift([1500,1120,1650],50,p),[1500,1100,1670])
    def test_two_side_presets_use_equal_safe_stroke_and_allow_independent_reduction(self):
        p=self.profile([-1,1]);p['manual_neck_reference_us']=[1500,1270,1500]
        a=rod_preset(1500,1,-1,p);b=rod_preset(1500,-1,1,p)
        self.assertEqual([abs(a[i]-p['manual_neck_reference_us'][i]) for i in (1,2)],[170,170])
        self.assertEqual([abs(b[i]-p['manual_neck_reference_us'][i]) for i in (1,2)],[170,170])
        p['side_preset_spans_us']={'left_up_right_down':170,'left_down_right_up':140}
        self.assertEqual(rod_preset(1500,-1,1,p),[1500,1410,1640])
if __name__=='__main__':unittest.main(verbosity=2)