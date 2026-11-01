import contextlib,io,json,sys,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/"src/pc"));sys.path.insert(0,str(ROOT/"sim"))
import pitch_pin10_compare as probe
import test_vertical_feedback as fixtures
class Tests(unittest.TestCase):
    def test_default_no_commands(self):
        with patch.object(sys,"argv",["compare"]),patch.object(probe,"Client") as client,contextlib.redirect_stdout(io.StringIO()):probe.main()
        client.assert_not_called()
    def test_loaded_pitch_comparison_never_uses_wide_yaw_range(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);(root/"build").mkdir()
            (root/"build/diagnostic_wiring.json").write_text(json.dumps({"state":"vertical_on_pin10_operator_confirmed"}))
            fixtures.EyeClient.instances=[]
            with patch.object(sys,"argv",["compare","--run","--operator-ready"]),patch.object(probe,"ROOT",root),patch.object(probe,"Client",fixtures.EyeClient),patch.object(probe.time,"sleep"),contextlib.redirect_stdout(io.StringIO()):probe.main()
            r=json.loads(next((root/"build").glob("pitch_on_pin10_*.result.json")).read_text(encoding="utf-8"))
            self.assertEqual(r["digital_endpoints_us"],[1500,1450,1500,1550,1500])
            self.assertEqual(r["final"]["active_mask"],0)
            self.assertTrue(all(1450<=v["requested_us"]<=1550 for v in r["samples"]))
            self.assertTrue(all(int.from_bytes(p[8:12],"little")==1 for p in fixtures.EyeClient.instances[-1].packets if p[:2]==b"NH"))
if __name__=="__main__":unittest.main(verbosity=2)
