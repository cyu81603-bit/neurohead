import contextlib,io,json,sys,tempfile,time,unittest
from pathlib import Path
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/"src/pc"));sys.path.insert(0,str(ROOT/"sim"))
import eye_camera_feedback as runner
import test_vertical_feedback as fixtures
import test_eye_feedback_runner as helpers
class Tests(unittest.TestCase):
    args=helpers.RunnerTests.args
    def test_emitted_pitch_commands_are_effective_steps_and_stop(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);(root/"build").mkdir();stop=root/"stop";p=root/"vertical.json"
            p.write_text(json.dumps({"channel":1,"assembled_at_1500_operator_confirmed":True,
                "initial_tracking_requested_by_operator":True,"simultaneous_tracking_requested_by_operator":True,
                "development_feedback_limits_us":[1400,1600],"development_max_rate_us_per_s":100,
                "output_quantum_us":10,"output_slew_us_per_frame":10}))
            count=[0];fixtures.EyeClient.instances=[]
            def camera(_):
                count[0]+=1;i=count[0]
                if i==1000:stop.write_text("stop")
                now=time.monotonic()
                return {"stream_duration_s":0,"host_monotonic_s":now,"vision":{
                    "frame_id":i,"frame_time":i*.05,"target":[.2,.2 if i<450 else -.2],
                    "camera_index":"USB Cam","detector":"yunet_2023mar","running":True,"source_session_id":"test"}}
            args=self.args(stop)+["--continuous","--axis","both","--vertical-profile",str(p)]
            with patch.object(sys,"argv",args),patch.object(runner,"ROOT",root),patch.object(runner,"Client",fixtures.EyeClient),patch.object(runner,"latest",camera),patch.object(runner,"visual_pulse",return_value=1500),patch.object(runner.time,"sleep"),contextlib.redirect_stdout(io.StringIO()):
                runner.main()
            r=json.loads(next((root/"build").glob("eye_pilot_*.result.json")).read_text(encoding="utf-8"))
            values=[v["requested_by_channel"]["1"] for v in r["samples"]]
            differences=[b-a for a,b in zip(values,values[1:]) if a!=b]
            self.assertTrue(differences);self.assertTrue(all(abs(v)==10 for v in differences))
            self.assertTrue(any(v>0 for v in differences) and any(v<0 for v in differences))
            self.assertEqual(min(values),1400);self.assertEqual(max(values),1600)
            self.assertEqual(r["vertical_output"]["hardware_slew_us_per_frame"],10)
            self.assertEqual(r["final"]["active_mask"],0)
    def test_finite_trial_returns_both_settings_to_neutral(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);(root/"build").mkdir();p=root/"vertical.json"
            p.write_text(json.dumps({"channel":1,"assembled_at_1500_operator_confirmed":True,
                "initial_tracking_requested_by_operator":True,"simultaneous_tracking_requested_by_operator":True,
                "development_feedback_limits_us":[1400,1600],"development_max_rate_us_per_s":100}))
            counter=[0];fixtures.EyeClient.instances=[]
            def camera(_):
                counter[0]+=1;now=time.monotonic()
                return {"host_monotonic_s":now,"vision":{"frame_id":counter[0],"frame_time":counter[0]*.05,
                    "target":[.5,.5],"camera_index":"USB Cam","detector":"yunet_2023mar",
                    "running":True,"source_session_id":"test"}}
            args=self.args()+["--axis","both","--vertical-profile",str(p)]
            with patch.object(sys,"argv",args),patch.object(runner,"ROOT",root),patch.object(runner,"Client",fixtures.EyeClient),patch.object(runner,"latest",camera),patch.object(runner,"visual_pulse",return_value=1500),patch.object(runner.time,"sleep"),contextlib.redirect_stdout(io.StringIO()):
                runner.main()
            r=json.loads(next((root/"build").glob("eye_pilot_*.result.json")).read_text(encoding="utf-8"))
            self.assertEqual(r["motion_frames"],400)
            self.assertEqual(r["samples"][-1]["output_by_channel"],{"0":1500,"1":1500})
            self.assertEqual(r["final"]["active_mask"],0)
if __name__=="__main__":unittest.main(verbosity=2)
