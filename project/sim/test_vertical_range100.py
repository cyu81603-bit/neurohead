import contextlib,io,json,statistics,sys,tempfile,time,unittest
from pathlib import Path
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/"src/pc"));sys.path.insert(0,str(ROOT/"sim"))
import eye_camera_feedback as runner
from eye_vertical_settings import vertical_settings
import test_vertical_feedback as fixtures
import test_eye_feedback_runner as helpers
class Tests(unittest.TestCase):
    args=helpers.RunnerTests.args
    def test_same_law_dual_center_tracking_with_expanded_pitch(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);(root/"build").mkdir();stop=root/"stop";p=root/"vertical.json"
            p.write_text(json.dumps({"channel":1,"assembled_at_1500_operator_confirmed":True,
                "initial_tracking_requested_by_operator":True,"simultaneous_tracking_requested_by_operator":True,
                "development_feedback_limits_us":[1400,1600],"development_max_rate_us_per_s":100}))
            count=[0];fixtures.EyeClient.instances=[]
            def camera(_):
                count[0]+=1;i=count[0]
                if i==1100:stop.write_text("stop")
                u=fixtures.EyeClient.instances[-1].output if fixtures.EyeClient.instances else [1500]*22
                x=(.3 if i<500 else -.3)+.002*(u[0]-1500)
                y=(.18 if i<600 else -.18)+.002*(u[1]-1500)
                now=time.monotonic()
                return {"stream_duration_s":0,"host_monotonic_s":now,"vision":{
                    "frame_id":i,"frame_time":i*.05,"target":[x,y],"camera_index":"USB Cam",
                    "detector":"yunet_2023mar","running":True,"source_session_id":"test"}}
            args=self.args(stop)+["--continuous","--axis","both","--vertical-profile",str(p)]
            with patch.object(sys,"argv",args),patch.object(runner,"ROOT",root),patch.object(runner,"Client",fixtures.EyeClient),patch.object(runner,"latest",camera),patch.object(runner,"visual_pulse",return_value=1500),patch.object(runner.time,"sleep"),contextlib.redirect_stdout(io.StringIO()):
                runner.main()
            r=json.loads(next((root/"build").glob("eye_pilot_*.result.json")).read_text(encoding="utf-8"));s=r["samples"]
            self.assertEqual(r["vertical_reference_method"],"image_center");self.assertEqual(r["vertical_reference_y"],0)
            self.assertEqual(r["feedback_settings"]["1"]["limits_us"],[1400,1600])
            self.assertEqual(r["feedback_settings"]["1"]["max_rate_us_per_s"],100)
            pitch=[v["requested_by_channel"]["1"] for v in s]
            self.assertLess(min(pitch),1450);self.assertGreater(max(pitch),1550)
            self.assertTrue(all(1400<=v<=1600 for v in pitch))
            self.assertLess(abs(statistics.median(v["face_x"] for v in s[-40:])),.05)
            self.assertLess(abs(statistics.median(v["face_y"] for v in s[-40:])),.05)
            self.assertEqual(r["final"]["active_mask"],0)
            configs=[p for p in fixtures.EyeClient.instances[-1].packets if p[:2]==b"NC" and p[8]==1]
            self.assertEqual(int.from_bytes(configs[0][10:12],"little"),1400)
            self.assertEqual(int.from_bytes(configs[0][12:14],"little"),1600)
            self.assertEqual(int.from_bytes(configs[0][16:18],"little"),10)
    def test_uncalibrated_broad_limits_rejected(self):
        with self.assertRaises(ValueError):vertical_settings({"development_feedback_limits_us":[600,2400]})
if __name__=="__main__":unittest.main(verbosity=2)
