import unittest,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"src/pc"))
import vision_bridge
class VisionTests(unittest.TestCase):
 def setUp(self):
  self.rows=[dict(id="F01",channel=0,enabled=True,mechanical_verified=True,
                   min_us=1490,max_us=1510,neutral_us=1500)]
  self.mapping={"axes":[dict(id="F01",coordinate="x",gain_us=10)]}
  self.sample={"host_monotonic_s":10,"vision":{"running":True,"frame_time":10,
                "source_session_id":"abc","target":[1,-1]}}
 def test_position_and_neutral(self):
  mask,pulses,sid=vision_bridge.sample_to_pose(self.sample,self.rows,self.mapping,10.1)
  self.assertEqual((mask,pulses[0],sid),(1,1510,"abc"))
  self.sample["vision"]["target"]=None
  self.assertEqual(vision_bridge.sample_to_pose(self.sample,self.rows,self.mapping,10.1)[1][0],1500)
 def test_stale_source_nan_and_unverified(self):
  with self.assertRaises(ValueError):vision_bridge.sample_to_pose(self.sample,self.rows,self.mapping,11)
  with self.assertRaises(ValueError):vision_bridge.sample_to_pose(self.sample,self.rows,self.mapping,10.1,"other")
  self.sample["vision"]["target"]=[float("nan"),0]
  with self.assertRaises(ValueError):vision_bridge.sample_to_pose(self.sample,self.rows,self.mapping,10.1)
  self.sample["vision"]["target"]=[0,0];self.rows[0]["mechanical_verified"]=False
  with self.assertRaises(ValueError):vision_bridge.sample_to_pose(self.sample,self.rows,self.mapping,10.1)
if __name__=="__main__":unittest.main(verbosity=2)
