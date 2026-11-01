import contextlib,io,json,sys,tempfile,time,unittest
from pathlib import Path
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"src/pc"))
sys.path.insert(0,str(ROOT/"sim"))
import eye_camera_feedback as runner
from test_eye_span import FakeClient

class RunnerTests(unittest.TestCase):
    def args(self,stop_file=None):
        result=["eye_camera_feedback.py","pilot","--run","--operator-ready",
                "--span-evidence",str(ROOT/"build/loaded_visible_20261025_120014.result.json"),
                "--direction-evidence",str(ROOT/"build/provisional_eye_feedback_direction.json")]
        if stop_file:result+=["--stop-file",str(stop_file)]
        return result
    def camera(self,stop_file=None,stop_after=None):
        counter=[0]
        def latest(_):
            counter[0]+=1
            if stop_after and counter[0]==stop_after:stop_file.write_text("stop")
            now=time.monotonic()
            return {"stream_duration_s":0,"host_monotonic_s":now,"vision":{"camera_index":"USB Cam","detector":"yunet_2023mar",
                "running":True,"source_session_id":"test","frame_time":10+counter[0]*.05,
                "frame_id":counter[0],"target":[.3,0]}}
        return latest
    def test_default_no_network_or_lock(self):
        with patch.object(sys,"argv",["runner","pilot"]),patch.object(runner,"Client") as client,patch.object(runner,"acquire_run_lock") as lock,contextlib.redirect_stdout(io.StringIO()):
            runner.main()
        client.assert_not_called();lock.assert_not_called()
    def test_full_finite_run_stops_and_restores(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);(root/"build").mkdir()
            FakeClient.fail_at=None;FakeClient.instances=[]
            with patch.object(sys,"argv",self.args()),patch.object(runner,"ROOT",root),patch.object(runner,"Client",FakeClient),patch.object(runner,"latest",self.camera()),patch.object(runner.time,"sleep"),patch.object(runner,"visual_pulse",return_value=1500),contextlib.redirect_stdout(io.StringIO()):
                runner.main()
            result=json.loads(next((root/"build").glob("eye_pilot_*.result.json")).read_text())
            self.assertEqual(result["motion_frames"],400)
            self.assertTrue(result["digital_checks_passed"])
            self.assertEqual([p[:2] for p in FakeClient.instances[-1].packets[-2:]],[b"NS",b"NC"])
    def test_stop_before_preflight_never_constructs_client(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);(root/"build").mkdir();stop=root/"stop";stop.write_text("stop")
            with patch.object(sys,"argv",self.args(stop)),patch.object(runner,"ROOT",root),patch.object(runner,"Client") as client,contextlib.redirect_stdout(io.StringIO()):
                with self.assertRaisesRegex(RuntimeError,"operator stop requested"):runner.main()
            client.assert_not_called()
    def test_mid_run_stop_acknowledged(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);(root/"build").mkdir();stop=root/"stop"
            FakeClient.fail_at=None;FakeClient.instances=[]
            with patch.object(sys,"argv",self.args(stop)),patch.object(runner,"ROOT",root),patch.object(runner,"Client",FakeClient),patch.object(runner,"latest",self.camera(stop,6)),patch.object(runner.time,"sleep"),patch.object(runner,"visual_pulse",return_value=1500),contextlib.redirect_stdout(io.StringIO()):
                with self.assertRaisesRegex(RuntimeError,"operator stop requested"):runner.main()
            result=json.loads(next((root/"build").glob("eye_pilot_*.result.json")).read_text())
            self.assertLess(result["motion_frames"],400)
            self.assertEqual(result["final"]["active_mask"],0)
            self.assertEqual(result["interruption_reason"],"operator stop requested")
            self.assertNotIn("digital_checks_passed",result)
    def test_second_run_lock_refused(self):
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/"lock";first=runner.acquire_run_lock(path)
            try:
                with self.assertRaisesRegex(RuntimeError,"already active"):runner.acquire_run_lock(path)
            finally:first.close()
if __name__=="__main__":unittest.main(verbosity=2)
