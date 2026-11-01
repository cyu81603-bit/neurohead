import contextlib,io,json,os,sys,tempfile,time,unittest
from pathlib import Path
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"src/pc"));sys.path.insert(0,str(ROOT/"sim"))
import eye_camera_feedback as runner
from runtime_logs import JsonlLog
from test_eye_feedback_runner import RunnerTests
from test_eye_span import FakeClient
class ContinuousTests(unittest.TestCase):
    args=RunnerTests.args
    camera=RunnerTests.camera
    def test_continues_beyond_20s_and_bounds_memory(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);(root/"build").mkdir();stop=root/"stop"
            FakeClient.fail_at=None;FakeClient.instances=[]
            args=self.args(stop)+["--continuous"]
            with patch.object(sys,"argv",args),patch.object(runner,"ROOT",root),patch.object(runner,"Client",FakeClient),patch.object(runner,"latest",self.camera(stop,1608)),patch.object(runner.time,"sleep"),patch.object(runner,"visual_pulse",return_value=1500),contextlib.redirect_stdout(io.StringIO()):
                runner.main()
            result=json.loads(next((root/"build").glob("eye_pilot_*.result.json")).read_text(encoding="utf-8"))
            self.assertGreater(result["motion_frames"],400)
            self.assertEqual(result["retained_samples"],1200)
            self.assertTrue(result["stopped_by_operator"])
            self.assertEqual(result["final"]["active_mask"],0)
            self.assertTrue(all(s["requested_us"]!=1500 for s in result["samples"][-200:]))
    def test_panel_heartbeat_loss_stops_active_run(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);(root/"build").mkdir();stop=root/"stop";heartbeat=root/"heartbeat";heartbeat.touch()
            camera=self.camera();count=[0]
            def latest(path):
                count[0]+=1
                if count[0]==7:os.utime(heartbeat,(0,0))
                return camera(path)
            FakeClient.fail_at=None;FakeClient.instances=[]
            with patch.object(sys,"argv",self.args(stop)+["--continuous","--heartbeat-file",str(heartbeat)]),patch.object(runner,"ROOT",root),patch.object(runner,"Client",FakeClient),patch.object(runner,"latest",latest),patch.object(runner.time,"sleep"),patch.object(runner,"visual_pulse",return_value=1500),contextlib.redirect_stdout(io.StringIO()):
                with self.assertRaisesRegex(RuntimeError,"heartbeat lost"):runner.main()
            result=json.loads(next((root/"build").glob("eye_pilot_*.result.json")).read_text(encoding="utf-8"))
            self.assertGreater(result["motion_frames"],0)
            self.assertEqual(result["final"]["active_mask"],0)
    def test_continuous_requires_stop_path(self):
        with patch.object(sys,"argv",self.args()+["--continuous"]),patch.object(runner,"Client") as client,contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit):runner.main()
        client.assert_not_called()
    def test_no_face_waits_past_20s_then_reacquires(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);(root/"build").mkdir();stop=root/"stop"
            base=self.camera(stop,710);count=[0]
            def camera(path):
                count[0]+=1;row=base(path)
                if count[0]<500:row["vision"]["target"]=None
                return row
            FakeClient.fail_at=None;FakeClient.instances=[]
            with patch.object(sys,"argv",self.args(stop)+["--continuous"]),patch.object(runner,"ROOT",root),patch.object(runner,"Client",FakeClient),patch.object(runner,"latest",camera),patch.object(runner.time,"sleep"),patch.object(runner,"visual_pulse",return_value=1500),contextlib.redirect_stdout(io.StringIO()):
                runner.main()
            result=json.loads(next((root/"build").glob("eye_pilot_*.result.json")).read_text(encoding="utf-8"))
            self.assertGreater(result["motion_frames"],400)
            self.assertTrue(all(s["requested_us"]==1500 for s in result["samples"][:450]))
            self.assertTrue(any(s["requested_us"]!=1500 for s in result["samples"][500:]))
            self.assertEqual(result["final"]["active_mask"],0)

    def test_rotating_log_remains_bounded(self):
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/"samples.jsonl"
            with JsonlLog(path,max_bytes=512,backups=2) as writer:
                for i in range(100):writer.write_row({"i":i,"data":"x"*80})
            files=list(Path(d).glob("samples.jsonl*"))
            self.assertLessEqual(len(files),3)
            self.assertLessEqual(sum(p.stat().st_size for p in files),1536)
if __name__=="__main__":unittest.main(verbosity=2)
