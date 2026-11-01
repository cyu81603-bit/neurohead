import contextlib,io,json,math,sys,tempfile,time,unittest
from pathlib import Path
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src/pc'));sys.path.insert(0,str(ROOT/'sim'))
from neck_identification import plan,analyze
import neck_visual_identify as runner
from test_vertical_feedback import EyeClient
class Tests(unittest.TestCase):
    def samples(self,J):
        phases=plan();rows=[];frame=0
        for i,p in enumerate(phases):
            motion=[0.]*3 if i==0 else [J[r][p['motor']]*p['delta_us'] for r in range(3)]
            count=20;dt=p['duration_s']/count
            for _ in range(count):
                frame+=1;rows.append(dict(phase=i,frame_id=frame,scene_motion=dict(valid=True,dt_s=dt,
                    dx_px=float(motion[0]*320/count),dy_px=float(motion[1]*240/count),roll_deg=float(math.degrees(motion[2])/count))))
        return rows
    def test_measures_full_coupling_without_ideal_mixing_assumption(self):
        J=[[.002,.0002,-.0001],[.0001,.0015,.0012],[0,.0007,-.0009]]
        result=analyze(plan(),self.samples(J))
        self.assertTrue(result['valid'])
        for r in range(3):
            for c in range(3):
                self.assertAlmostEqual(result['jacobian'][r][c],J[r][c],delta=1e-10)
                value=sum(result['inverse_jacobian'][r][k]*J[k][c] for k in range(3))
                self.assertAlmostEqual(value,1 if r==c else 0,delta=1e-10)
    def test_parallel_actuator_effects_are_not_declared_three_axes(self):
        J=[[.002,0,0],[0,.001,.001],[0,0,0]]
        result=analyze(plan(),self.samples(J))
        self.assertFalse(result['valid']);self.assertIn('independent',result['reason'])
    def test_default_no_network(self):
        with patch.object(sys,'argv',['identify']),patch.object(runner,'Client') as client,contextlib.redirect_stdout(io.StringIO()):
            runner.main();client.assert_not_called()
    def test_bad_background_stops_at_neutral_without_test_offsets(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);(root/'config').mkdir();(root/'build').mkdir()
            (root/'config/neck_follow.json').write_text(json.dumps({'pair_common_loaded_span_operator_verified':True,'eye_camera_rigidly_on_head_operator_confirmed':True}))
            count=[0];EyeClient.instances=[]
            def camera(_):
                count[0]+=1;now=time.monotonic()
                return dict(host_monotonic_s=now,scene_motion={'valid':False},vision=dict(camera_index='USB Cam',
                    detector='yunet_2023mar',running=True,source_session_id='test',frame_time=now,frame_id=count[0],target=None))
            with patch.object(sys,'argv',['identify','--run','--operator-ready','--head-supported']),\
                 patch.object(runner,'ROOT',root),patch.object(runner,'latest',camera),patch.object(runner,'Client',EyeClient),\
                 patch.object(runner.time,'sleep'),contextlib.redirect_stdout(io.StringIO()):runner.main()
            packets=EyeClient.instances[-1].packets
            import struct
            for p in packets:
                if p[:2]==b'NH':
                    u=struct.unpack_from('<22H',p,12)
                    self.assertTrue(all(u[c]==1500 for c in (0,1,18,19,20)))
            result=json.loads(next((root/'build').glob('neck_identify*.json')).read_text(encoding='utf-8'))
            self.assertIn('quality insufficient',result['interruption_reason']);self.assertNotIn('digital_checks_passed',result)
            self.assertEqual(result['final']['active_mask'],0)
if __name__=='__main__':unittest.main(verbosity=2)