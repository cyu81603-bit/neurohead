import contextlib,io,json,struct,sys,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src/pc'));sys.path.insert(0,str(ROOT/'sim'))
import neck_yaw_midpoint as neck
import eye_camera_feedback as eye
from test_vertical_feedback import EyeClient
from test_eye_feedback_runner import RunnerTests
class IdleNeckClient(EyeClient):
    def exchange(self,p):
        state=super().exchange(p);state['configured_mask']=3|(1<<18);return state
class BusyNeckClient(IdleNeckClient):
    def __init__(self,**kwargs):
        super().__init__(**kwargs);self.active=1<<18
class Tests(unittest.TestCase):
    def test_neck_dryrun_and_missing_physical_conditions_never_connect(self):
        with patch.object(sys,'argv',['neck']),patch.object(neck,'Client') as client,contextlib.redirect_stdout(io.StringIO()):
            neck.main();client.assert_not_called()
        with patch.object(sys,'argv',['neck','--run','--operator-ready']),patch.object(neck,'Client') as client:
            with self.assertRaisesRegex(ValueError,'decoupled'):neck.main()
            client.assert_not_called()
    def test_neck_midpoint_drives_only_yaw_and_stops(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);(root/'build').mkdir();EyeClient.instances=[]
            with patch.object(sys,'argv',['neck','--run','--operator-ready','--decoupled','--head-supported']),\
                 patch.object(neck,'ROOT',root),patch.object(neck,'Client',EyeClient),\
                 patch.object(neck.time,'sleep'),contextlib.redirect_stdout(io.StringIO()):neck.main()
            packets=EyeClient.instances[-1].packets
            commands=[p for p in packets if p[:2]==b'NH']
            self.assertEqual(len(commands),40)
            for p in commands:
                self.assertEqual(int.from_bytes(p[8:12],'little'),1<<18)
                pulses=struct.unpack_from('<22H',p,12)
                self.assertEqual(pulses[18],1500)
                self.assertTrue(all(v==0 for i,v in enumerate(pulses) if i!=18))
            self.assertEqual(packets[-1][:2],b'NS')
            result=json.loads(next((root/'build').glob('neck_yaw*.json')).read_text(encoding='utf-8'))
            self.assertTrue(result['digital_checks_passed'])
            self.assertFalse(result['mechanical_forward_reference_verified'])
            self.assertEqual(result['final']['active_mask'],0)
    def test_neck_busy_preflight_does_not_stop_a_running_controller(self):
        BusyNeckClient.instances=[]
        with patch.object(sys,'argv',['neck','--run','--operator-ready','--decoupled','--head-supported']),\
             patch.object(neck,'Client',BusyNeckClient),contextlib.redirect_stdout(io.StringIO()):
            with self.assertRaisesRegex(RuntimeError,'no actuator writes'):neck.main()
        self.assertEqual([p[:2] for p in BusyNeckClient.instances[-1].packets],[b'NQ'])
    def eye_session(self,client,expect_busy):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);(root/'build').mkdir();client.instances=[]
            args=RunnerTests.args(self)
            with patch.object(sys,'argv',args),patch.object(eye,'ROOT',root),patch.object(eye,'Client',client),\
                 patch.object(eye,'latest',RunnerTests.camera(self)),patch.object(eye.time,'sleep'),\
                 patch.object(eye,'visual_pulse',return_value=1500),contextlib.redirect_stdout(io.StringIO()):
                if expect_busy:
                    with self.assertRaisesRegex(ValueError,'no actuator writes'):eye.main()
                else:eye.main()
            return client.instances[-1].packets
    def test_eye_refuses_active_neck_without_stop(self):
        packets=self.eye_session(BusyNeckClient,True)
        self.assertEqual([p[:2] for p in packets],[b'NQ'])
    def test_eye_can_run_after_neck_test_when_neck_is_inactive(self):
        packets=self.eye_session(IdleNeckClient,False)
        self.assertEqual(packets[-1][:2],b'NC')
        self.assertTrue(any(p[:2]==b'NH' for p in packets))
        self.assertTrue(all(int.from_bytes(p[8:12],'little')==1 for p in packets if p[:2]==b'NH'))
    def test_loaded_first_pulse_is_four_fixed_midpoint_frames_and_stop(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);(root/'build').mkdir();(root/'config').mkdir()
            (root/'config/neck_follow.json').write_text(json.dumps({'loaded_first_pulse_requested_by_operator':True}))
            EyeClient.instances=[]
            with patch.object(sys,'argv',['neck','--run','--operator-ready','--loaded-first-pulse','--head-supported']),\
                 patch.object(neck,'ROOT',root),patch.object(neck,'Client',EyeClient),\
                 patch.object(neck.time,'sleep'),contextlib.redirect_stdout(io.StringIO()):neck.main()
            packets=EyeClient.instances[-1].packets
            commands=[p for p in packets if p[:2]==b'NH']
            self.assertEqual(len(commands),4)
            self.assertTrue(all(int.from_bytes(p[8:12],'little')==1<<18 for p in commands))
            self.assertTrue(all(struct.unpack_from('<22H',p,12)[18]==1500 for p in commands))
            self.assertEqual(packets[-1][:2],b'NS')
            result=json.loads(next((root/'build').glob('neck_yaw*.json')).read_text(encoding='utf-8'))
            self.assertEqual(result['duration_s'],.2)
            self.assertTrue(result['initial_shaft_position_unknown'])
            self.assertFalse(result['mechanical_forward_reference_verified'])
            self.assertEqual(result['final']['active_mask'],0)
    def test_loaded_mode_without_operator_request_never_connects(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);(root/'config').mkdir()
            (root/'config/neck_follow.json').write_text('{}')
            with patch.object(sys,'argv',['neck','--run','--operator-ready','--loaded-first-pulse','--head-supported']),\
                 patch.object(neck,'ROOT',root),patch.object(neck,'Client') as client:
                with self.assertRaisesRegex(ValueError,'operator request'):neck.main()
                client.assert_not_called()
if __name__=='__main__':unittest.main(verbosity=2)