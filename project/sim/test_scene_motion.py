import sys,unittest
from pathlib import Path
import numpy as np,cv2
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"src/pc"))
from scene_motion import SceneMotion
class Tests(unittest.TestCase):
    def test_background_translation(self):
        rng=np.random.default_rng(5);a=rng.integers(0,255,(480,640,3),dtype=np.uint8)
        b=cv2.warpAffine(a,np.array([[1,0,-2],[0,1,4]],dtype=float),(640,480))
        m=SceneMotion();self.assertFalse(m.update(a,[260,120,100,130],0)["valid"])
        result=m.update(b,[260,120,100,130],.0667)
        self.assertTrue(result["valid"]);self.assertAlmostEqual(result["dy_px"],4,delta=.3)
        self.assertAlmostEqual(result["dx_px"],-2,delta=.3)
    def test_moving_face_does_not_define_camera_motion(self):
        rng=np.random.default_rng(6);a=rng.integers(0,255,(480,640,3),dtype=np.uint8);b=a.copy()
        b[140:320,230:420]=255
        m=SceneMotion();m.update(a,[250,150,100,140],0)
        result=m.update(b,[250,170,100,140],.0667)
        self.assertTrue(result["valid"]);self.assertAlmostEqual(result["dy_px"],0,delta=.1)
    def test_blank_background_not_guessed(self):
        a=np.zeros((480,640,3),dtype=np.uint8);m=SceneMotion();m.update(a,None,0)
        self.assertFalse(m.update(a,None,.0667)["valid"])
    def test_rotation_is_separate_from_translation(self):
        rng=np.random.default_rng(9);a=rng.integers(0,255,(480,640,3),dtype=np.uint8)
        transform=cv2.getRotationMatrix2D((320,240),1.5,1)
        b=cv2.warpAffine(a,transform,(640,480))
        m=SceneMotion();m.update(a,None,0)
        result=m.update(b,None,.0667)
        self.assertTrue(result["valid"]);self.assertAlmostEqual(result["roll_deg"],-1.5,delta=.15)
        self.assertAlmostEqual(result["dy_px"],0,delta=.3)
if __name__=="__main__":unittest.main(verbosity=2)
