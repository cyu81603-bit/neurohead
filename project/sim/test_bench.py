import unittest,sys,struct
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"src/pc"))
import bench_mg90s,nh22
class BenchTests(unittest.TestCase):
 def test_bounds(self):
  frames=bench_mg90s.plan()
  self.assertEqual(len(frames),150)
  for i,values in enumerate(frames):
   self.assertEqual([n for n,v in enumerate(values) if v],[1])
   self.assertEqual(values[1],bench_mg90s.POINTS[i//30])
   self.assertLessEqual(abs(values[1]-1500),50)
   frame=nh22.motion(i+2,2,values)
   self.assertEqual(len(frame),60)
   self.assertEqual(struct.unpack_from("<I",frame,8)[0],2)
if __name__=="__main__":unittest.main(verbosity=2)
