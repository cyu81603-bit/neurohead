import sys,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"src/pc"))
from image_feedback import Feedback,estimate_jacobian
class Tests(unittest.TestCase):
    def test_converges_both_mounting_polarities(self):
        for j in (-.002,.002):
            c=Feedback(j)
            for i in range(200):
                x=.45+j*(c.pulse-1500)
                c.update(i,10+i*.0667,x)
            self.assertLess(abs(.45+j*(c.pulse-1500)),.05)
    def test_camera_moving_target_follow_and_limits(self):
        c=Feedback(.002)
        for i in range(300):
            world=.4 if i<100 else -.4
            c.update(i,10+i*.0667,world+.002*(c.pulse-1500))
        self.assertLess(abs(-.4+.002*(c.pulse-1500)),.05)
        for i in range(300,500):c.update(i,10+i*.0667,1.)
        self.assertEqual(c.pulse,1100)
    def test_repeated_frame_no_integration_and_loss_returns(self):
        c=Feedback(.002)
        c.update(1,10,.5);c.update(2,10.1,.5)
        before=c.pulse
        for i in range(50):c.update(2,10.1,.5)
        self.assertEqual(c.pulse,before)
        for i in range(3,100):c.update(i,10+i*.0667,None)
        self.assertEqual(c.pulse,1500)
    def test_calibration_sign_and_stationary_rejection(self):
        samples=[]
        for phase,u in enumerate((1500,1600,1500,1400,1500)):
            for i in range(12):
                samples.append({"phase":phase,"source_frame":phase*12+i,"phase_elapsed_s":.6+i*.05,
                    "output_us":u,"face_x":-.3+.002*(u-1500)})
        result=estimate_jacobian(samples)
        self.assertAlmostEqual(result["image_dx_per_us"],.002)
        self.assertEqual(result["feedback_sign"],-1)
        for s in samples:s["face_x"]=0
        with self.assertRaises(ValueError):estimate_jacobian(samples)
if __name__=="__main__":unittest.main(verbosity=2)
