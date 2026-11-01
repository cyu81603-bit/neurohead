import contextlib,hashlib,io,json,sys,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"src/pc"))
import visible_visual_trial as visible
class Tests(unittest.TestCase):
    def row(self,x):
        return {"host_monotonic_s":10,"vision":{"camera_index":"USB Cam","detector":"yunet_2023mar",
                "running":True,"source_session_id":"a","frame_time":10,"target":x}}
    def test_visible_bounded_continuous_direction(self):
        values=[visible.visible_pulse(self.row([x/1000,0]),10.1,"a") for x in range(-1000,1001)]
        self.assertEqual(min(values),1100);self.assertEqual(max(values),1900)
        self.assertEqual(values,sorted(values))
        self.assertGreater(visible.visible_pulse(self.row([.4,0]),10.1,"a")-1500,200)
        self.assertEqual(visible.visible_pulse(self.row([.05,0]),10.1,"a"),1500)
        self.assertEqual(visible.visible_pulse(self.row(None),10.1,"a"),1500)
        self.assertEqual(visible.visible_pulse(self.row([1,0]),10.1,"a",-1),1100)
    def test_stale_or_wrong_camera_refused(self):
        with self.assertRaises(ValueError):visible.visible_pulse(self.row([1,0]),11,"a")
        row=self.row([1,0]);row["vision"]["camera_index"]="USB2.0 HD UVC WebCam"
        with self.assertRaises(ValueError):visible.visible_pulse(row,10.1,"a")
    def test_default_dry_run_no_network(self):
        with patch.object(sys,"argv",["visible_visual_trial.py"]),patch.object(visible,"Client") as client,contextlib.redirect_stdout(io.StringIO()):
            visible.main()
        client.assert_not_called()
    def test_digital_only_span_refused(self):
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/"evidence.json"
            path.write_text(json.dumps({"purpose":"finite_same_linkage_visible_span_check","limits_us":[1000,2000],
                "digital_checks_passed":True,"original_eye_guard_unchanged":True}))
            session={"span_evidence":str(path),"span_evidence_sha256":hashlib.sha256(path.read_bytes()).hexdigest()}
            with self.assertRaises(ValueError):visible.validate_evidence(session)
if __name__=="__main__":unittest.main(verbosity=2)
