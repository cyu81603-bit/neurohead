"""Operator-requested equal command spans, independently limited pitch speed."""
import contextlib,io,json,sys,tempfile,time,unittest
from pathlib import Path
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src/pc'));sys.path.insert(0,str(ROOT/'sim'))
import eye_camera_feedback as runner
from eye_vertical_settings import vertical_settings
import test_vertical_feedback as fixtures
import test_eye_feedback_runner as helpers
class Tests(unittest.TestCase):
    limits=(1100,1900)
    def profile(self):
        return dict(channel=1,assembled_at_1500_operator_confirmed=True,
            initial_tracking_requested_by_operator=True,simultaneous_tracking_requested_by_operator=True,
            development_feedback_limits_us=list(self.limits),development_max_rate_us_per_s=100,
            matching_horizontal_span_requested_by_operator=True,output_quantum_us=10,output_slew_us_per_frame=10)
    def run_trial(self,continuous):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);(root/'build').mkdir();profile=root/'pitch.json';stop=root/'stop'
            profile.write_text(json.dumps(self.profile()),encoding='utf-8')
            count=[0];fixtures.EyeClient.instances=[]
            def camera(_):
                count[0]+=1;i=count[0]
                if continuous and i==1100:stop.write_text('stop')
                now=time.monotonic()
                return dict(stream_duration_s=0,host_monotonic_s=now,vision=dict(
                    frame_id=i,frame_time=i*.05,target=[.95,.95 if i<400 else -.95],
                    camera_index='USB Cam',detector='yunet_2023mar',running=True,source_session_id='test'))
            args=helpers.RunnerTests.args(self,stop if continuous else None)+[
                '--axis','both','--vertical-profile',str(profile)]
            if continuous:args+=['--continuous']
            with patch.object(sys,'argv',args),patch.object(runner,'ROOT',root),\
                 patch.object(runner,'Client',fixtures.EyeClient),patch.object(runner,'latest',camera),\
                 patch.object(runner,'visual_pulse',return_value=1500),patch.object(runner.time,'sleep'),\
                 contextlib.redirect_stdout(io.StringIO()):runner.main()
            result=json.loads(next((root/'build').glob('eye_pilot_*.result.json')).read_text(encoding='utf-8'))
            return result,fixtures.EyeClient.instances[-1].packets
    def test_explicit_request_required_for_new_span(self):
        p=self.profile();self.assertEqual(vertical_settings(p),(*self.limits,100))
        p.pop('matching_horizontal_span_requested_by_operator')
        with self.assertRaisesRegex(ValueError,'operator request'):vertical_settings(p)
    def test_both_pitch_endpoints_and_channel_configuration(self):
        result,packets=self.run_trial(True)
        commands=[s['requested_by_channel']['1'] for s in result['samples']]
        self.assertEqual((min(commands),max(commands)),self.limits)
        self.assertTrue(all(self.limits[0]<=v<=self.limits[1] for v in commands))
        self.assertEqual(result['feedback_settings']['0']['max_rate_us_per_s'],200)
        self.assertEqual(result['feedback_settings']['1']['max_rate_us_per_s'],100)
        self.assertEqual(result['channel_mask'],3)
        configs=[p for p in packets if p[:2]==b'NC' and p[8]==1]
        self.assertEqual(int.from_bytes(configs[0][10:12],'little'),self.limits[0])
        self.assertEqual(int.from_bytes(configs[0][12:14],'little'),self.limits[1])
        self.assertEqual(result['final']['active_mask'],0)
    def test_finite_trial_recenters_both_after_wider_excursion(self):
        result,_=self.run_trial(False)
        self.assertTrue(result['digital_checks_passed'])
        self.assertEqual(result['samples'][-1]['output_by_channel'],{'0':1500,'1':1500})
        self.assertEqual(result['final']['active_mask'],0)
class ExpandedTests(Tests):
    limits=(1000,2000)
if __name__=='__main__':unittest.main(verbosity=2)