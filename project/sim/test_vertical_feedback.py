import contextlib,io,json,struct,sys,tempfile,time,unittest
from pathlib import Path
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/"src/pc"));sys.path.insert(0,str(ROOT/"sim"))
import eye_camera_feedback as runner
from image_feedback import Feedback
from test_eye_feedback_runner import RunnerTests
class EyeClient:
    instances=[]
    def __init__(self,**_):
        self.seq=0;self.active=0;self.output=[1500]*22;self.packets=[]
        self.__class__.instances.append(self)
    def next_sequence(self):self.seq+=1;return self.seq
    def exchange(self,p):
        self.packets.append(p)
        if p[:2]==b"NH":
            self.active=int.from_bytes(p[8:12],"little");values=struct.unpack_from("<22H",p,12)
            self.output=[values[i] if self.active&(1<<i) else 1500 for i in range(22)]
        if p[:2]==b"NS":self.active=0
        return {"sequence":self.seq,"status":5 if self.active else 0,"active_mask":self.active,
                "configured_mask":3,"output_us":list(self.output)}
    def close(self):pass
class Tests(unittest.TestCase):
    args=RunnerTests.args
    def profile(self,path):
        path.write_text(json.dumps({"channel":1,"assembled_at_1500_operator_confirmed":True,
            "initial_tracking_requested_by_operator":True,"basic_vertical_follow_operator_verified":False}))
    def test_vertical_uses_y_only_pin4_and_can_reverse(self):
        for reverse in (False,True):
            with tempfile.TemporaryDirectory() as d:
                root=Path(d);(root/"build").mkdir();p=root/"profile";self.profile(p)
                stop=root/"stop";counter=[0]
                def camera(_):
                    counter[0]+=1
                    if counter[0]==610:stop.write_text("stop")
                    now=time.monotonic()
                    return {"stream_duration_s":0,"host_monotonic_s":now,"vision":{
                        "frame_id":counter[0],"frame_time":counter[0]*.05,"target":[-.8,.3],
                        "camera_index":"USB Cam","detector":"yunet_2023mar","running":True,"source_session_id":"test"}}
                args=self.args(stop)+["--continuous","--axis","vertical","--vertical-profile",str(p)]
                if reverse:args+=["--vertical-reverse"]
                EyeClient.instances=[]
                with patch.object(sys,"argv",args),patch.object(runner,"ROOT",root),patch.object(runner,"Client",EyeClient),patch.object(runner,"latest",camera),patch.object(runner,"visual_pulse",return_value=1500),patch.object(runner.time,"sleep"),contextlib.redirect_stdout(io.StringIO()):
                    runner.main()
                result=json.loads(next((root/"build").glob("eye_pilot_*.result.json")).read_text(encoding="utf-8"))
                self.assertEqual(result["channel_mask"],2)
                self.assertEqual(result["final"]["active_mask"],0)
                values=[s["requested_us"] for s in result["samples"]]
                self.assertTrue(all(1450<=v<=1550 for v in values))
                self.assertEqual(values[-1],1550 if reverse else 1450)
                packets=[p for p in EyeClient.instances[-1].packets if p[:2]==b"NH"]
                self.assertTrue(all(int.from_bytes(p[8:12],"little")==2 and p[12:14]==b"\0\0" for p in packets))
    def test_combined_axis_blocked_before_vertical_observation(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/"profile";self.profile(p)
            with patch.object(sys,"argv",self.args()+["--axis","both","--vertical-profile",str(p)]),patch.object(runner,"Client") as client:
                with self.assertRaisesRegex(ValueError,"verify vertical"):runner.main()
            client.assert_not_called()
    def test_vertical_loss_respects_own_speed_and_envelope(self):
        c=Feedback(.002,gain=.8,max_rate=50,lo=1450,hi=1550)
        for i in range(100):c.update(i,i*.05,.3)
        previous=c.pulse
        c.update(100,5,None)
        self.assertLessEqual(c.pulse-previous,2.501)
        self.assertTrue(1450<=c.pulse<=1550)
if __name__=="__main__":unittest.main(verbosity=2)
