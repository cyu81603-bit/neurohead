import sys,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"src/pc"))
from effective_pulse import EffectivePulseOutput
class Tests(unittest.TestCase):
    def test_fine_changes_accumulate_then_emit(self):
        c=EffectivePulseOutput(1400,1600);values=[]
        for i in range(1,21):values.append(c.update(1500+i,i,i*.05))
        self.assertEqual(values[7],1500);self.assertEqual(values[9],1510);self.assertEqual(values[-1],1520)
    def test_bidirectional_bounded_and_rate_limited(self):
        c=EffectivePulseOutput(1400,1600);last=1500;emitted=[]
        for i in range(220):
            desired=1600 if i<100 else 1400
            value=c.update(desired,i,i*.05)
            self.assertTrue(1400<=value<=1600)
            if value!=last:emitted.append((i*.05,value));self.assertEqual(abs(value-last),10)
            last=value
        self.assertEqual(last,1400)
        for (ta,a),(tb,b) in zip(emitted,emitted[1:]):self.assertLessEqual(abs(b-a)/(tb-ta),100.00001)
    def test_duplicate_frame_does_not_advance(self):
        c=EffectivePulseOutput(1400,1600);c.update(1600,0,0);value=c.update(1600,1,.2)
        for i in range(10):self.assertEqual(c.update(1600,1,.2),value)
    def test_reversal_and_neutral_are_reachable(self):
        c=EffectivePulseOutput(1450,1550,max_rate_us_per_s=50)
        for i in range(80):c.update(1550,i,i*.05)
        self.assertEqual(c.command,1550)
        for i in range(80,180):c.update(1450,i,i*.05)
        self.assertEqual(c.command,1450)
        for i in range(180,260):c.update(1500,i,i*.05)
        self.assertEqual(c.command,1500)
if __name__=="__main__":unittest.main(verbosity=2)
