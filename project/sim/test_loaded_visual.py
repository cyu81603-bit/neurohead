import unittest,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"src/pc"))
from loaded_visual_trial import visual_pulse
class Tests(unittest.TestCase):
 def row(self,x):
  return {"host_monotonic_s":10,"vision":{"camera_index":"USB Cam","detector":"yunet_2023mar",
          "running":True,"source_session_id":"abc","frame_time":10,"target":x}}
 def test_only_verified_points(self):
  for x,expected in (([-1,0],1495),([0,0],1500),([1,0],1505),(None,1500)):
   self.assertEqual(visual_pulse(self.row(x),10.1,"abc"),expected)
 def test_bad_source(self):
  with self.assertRaises(ValueError):visual_pulse(self.row([0,0]),11,"abc")
  with self.assertRaises(ValueError):visual_pulse(self.row([0,0]),10.1,"other")
  r=self.row([0,0]);r["vision"]["camera_index"]=0
  with self.assertRaises(ValueError):visual_pulse(r,10.1,"abc")
  with self.assertRaises(ValueError):visual_pulse(self.row([float("nan"),0]),10.1,"abc")
if __name__=="__main__":unittest.main(verbosity=2)
