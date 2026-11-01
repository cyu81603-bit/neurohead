import unittest,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"src/pc"))
import loaded_step,bench_mg90s
class Tests(unittest.TestCase):
 def test_loaded_bounds(self):
  for delta in (-5,5):
   values=loaded_step.frames(delta)
   self.assertEqual(len(values),40)
   self.assertTrue(set(values)<=set((1500,1500+delta)))
   self.assertEqual(values[:8],[1500]*8)
   self.assertEqual(values[-16:],[1500]*16)
  with self.assertRaises(ValueError):loaded_step.frames(6)
 def test_reference_pattern_single_pin10(self):
  frames=bench_mg90s.plan(0,True)
  self.assertEqual(len(frames),280)
  for values in frames:
   self.assertEqual([i for i,v in enumerate(values) if v],[0])
   self.assertTrue(1000<=values[0]<=2000)
  self.assertEqual([frames[i][0] for i in (19,89,209,279)],[1500,2000,1000,1500])
if __name__=="__main__":unittest.main(verbosity=2)
