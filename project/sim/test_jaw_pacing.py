import sys,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src/pc'))
from jaw_unloaded_trial import trajectory

class Pacing(unittest.TestCase):
    def test_slow_paced_steps_reach_non_grid_endpoints_and_return(self):
        f=trajectory(position_check=True,mounted_target=1200,mounted_rate=100,mounted_settle=5,mounted_reference=1525,mounted_quantum=10)
        self.assertEqual(min(f),1200);self.assertEqual(max(f),1525)
        self.assertEqual(f[:250],[1525]*250);self.assertEqual(f[-250:],[1525]*250)
        transitions=[(i,v) for i,v in enumerate(f) if i==0 or v!=f[i-1]]
        self.assertEqual(transitions[-1][1],1525)
        for (a,x),(b,y) in zip(transitions,transitions[1:]):
            self.assertGreaterEqual(abs(y-x),10);self.assertLess(abs(y-x),20)
            self.assertLessEqual(abs(y-x)/((b-a)*.02),100.00001)
    def test_legacy_rate_path_is_unchanged(self):
        f=trajectory(position_check=True,mounted_target=1200,mounted_rate=100,mounted_reference=1525)
        self.assertTrue(all(abs(b-a)<=2 for a,b in zip(f,f[1:])))

if __name__=='__main__':unittest.main()
