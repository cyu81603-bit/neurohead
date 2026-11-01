"""Offline endpoint-search checks; no hardware connection."""
import json,subprocess,sys,unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src/pc'))
from jaw_unloaded_trial import trajectory
class SeekTests(unittest.TestCase):
    def test_search_finishes_at_target_without_return(self):
        f=trajectory(mounted_target=1150,mounted_rate=100,mounted_settle=2,mounted_reference=1200,mounted_target_hold=8,return_reference=False)
        self.assertEqual(len(f),525)
        self.assertEqual(f[-400:],[1150]*400)
        self.assertTrue(all(1150<=x<=1200 for x in f))
        self.assertTrue(all(abs(a-b)<=2 for a,b in zip(f,f[1:])))
    def test_legacy_round_trip_still_returns(self):
        f=trajectory(mounted_target=1300,mounted_rate=100,mounted_settle=2,mounted_reference=1200,mounted_target_hold=8)
        self.assertEqual(f[-100:],[1200]*100)
    def test_unloaded_confirmation_required_before_io(self):
        r=subprocess.run([sys.executable,'-B',str(ROOT/'src/pc/jaw_unloaded_trial.py'),'--unloaded-seek-target','1150','--run'],capture_output=True,text=True)
        self.assertEqual(r.returncode,2)
        self.assertIn('Seek requires unloaded',r.stderr)
if __name__=='__main__':unittest.main()
