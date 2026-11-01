import contextlib,io,json,statistics,sys,tempfile,time,unittest
from pathlib import Path
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/"src/pc"));sys.path.insert(0,str(ROOT/"sim"))
import eye_camera_feedback as runner
from eye_reference import StartupVerticalReference
import test_vertical_feedback as fixtures
import test_eye_feedback_runner as helpers
class Tests(unittest.TestCase):
    args=helpers.RunnerTests.args
    def test_reference_requires_distinct_settled_frames(self):
        ref=StartupVerticalReference()
        for _ in range(10):self.assertIsNone(ref.observe(1,0,.25))
        self.assertIsNone(ref.observe(2,.9,None))
        for i in range(3,7):self.assertIsNone(ref.observe(i,.9+i*.05,.25))
        self.assertEqual(ref.observe(7,1.3,.25),.25)
    def test_dual_axis_tracks_without_initial_vertical_drift(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);(root/"build").mkdir();stop=root/"stop";profile=root/"vertical.json"
            profile.write_text(json.dumps({"channel":1,"assembled_at_1500_operator_confirmed":True,
                "initial_tracking_requested_by_operator":True,"simultaneous_tracking_requested_by_operator":True,
                "basic_vertical_follow_operator_verified":False}))
            counter=[0];fixtures.EyeClient.instances=[]
            def camera(_):
                counter[0]+=1;i=counter[0]
                if i==1000:stop.write_text("stop")
                u=fixtures.EyeClient.instances[-1].output if fixtures.EyeClient.instances else [1500]*22
                x=(.3 if i<600 else -.3)+.002*(u[0]-1500)
                y=.25+(.07 if i>=450 else 0)-.002*(u[1]-1500)
                now=time.monotonic()
                return {"stream_duration_s":0,"host_monotonic_s":now,"vision":{
                    "frame_id":i,"frame_time":i*.05,"target":[x,y],"camera_index":"USB Cam",
                    "detector":"yunet_2023mar","running":True,"source_session_id":"test"}}
            args=self.args(stop)+["--continuous","--axis","both","--vertical-profile",str(profile),
                                 "--vertical-reverse","--vertical-reference-start"]
            with patch.object(sys,"argv",args),patch.object(runner,"ROOT",root),patch.object(runner,"Client",fixtures.EyeClient),patch.object(runner,"latest",camera),patch.object(runner,"visual_pulse",return_value=1500),patch.object(runner.time,"sleep"),contextlib.redirect_stdout(io.StringIO()):
                runner.main()
            result=json.loads(next((root/"build").glob("eye_pilot_*.result.json")).read_text(encoding="utf-8"))
            samples=result["samples"]
            self.assertEqual(result["channel_mask"],3);self.assertEqual(result["final"]["active_mask"],0)
            self.assertAlmostEqual(result["vertical_reference_y"],.25)
            self.assertTrue(all(s["requested_by_channel"]["1"]==1500 for s in samples[:350]))
            self.assertGreater(samples[-1]["requested_by_channel"]["1"],1500)
            self.assertLess(abs(statistics.median(s["face_x"] for s in samples[-50:])),.05)
            self.assertLess(abs(statistics.median(s["vertical_error"] for s in samples[-50:])),.05)
            packets=[p for p in fixtures.EyeClient.instances[-1].packets if p[:2]==b"NH"]
            self.assertTrue(all(int.from_bytes(p[8:12],"little")==3 for p in packets))
            self.assertTrue(all(1100<=s["requested_by_channel"]["0"]<=1900 and
                                1450<=s["requested_by_channel"]["1"]<=1550 for s in samples))
if __name__=="__main__":unittest.main(verbosity=2)
