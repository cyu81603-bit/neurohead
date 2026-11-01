import contextlib,io,sys,unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"src/pc"))
import diagnose_pitch_response as probe
class Tests(unittest.TestCase):
    def test_signed_background_response(self):
        for j in (-.002,.002):
            phases=[[]]
            for delta in (25,-25,-25,25):
                phases.append([{"scene_motion":{"valid":True,"dy_px":j*240*delta/20,"dx_px":0}} for _ in range(20)])
            result=probe.analyze(phases)
            self.assertTrue(result["valid"]);self.assertAlmostEqual(result["measured_image_dy_per_us"],j)
            self.assertEqual(result["reverse_required"],j<0)
    def test_no_response_not_claimed_calibrated(self):
        phases=[[]]+[[{"scene_motion":{"valid":True,"dy_px":0,"dx_px":0}}]*20 for _ in range(4)]
        self.assertFalse(probe.analyze(phases)["valid"])
    def test_default_no_hardware(self):
        with patch.object(sys,"argv",["probe"]),patch.object(probe,"Client") as client,contextlib.redirect_stdout(io.StringIO()):
            probe.main()
        client.assert_not_called()
if __name__=="__main__":unittest.main(verbosity=2)
