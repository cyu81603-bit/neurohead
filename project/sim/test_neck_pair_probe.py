import contextlib,io,json,struct,sys,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src/pc'));sys.path.insert(0,str(ROOT/'sim'))
import neck_pair_probe as probe
from test_vertical_feedback import EyeClient
class SlewClient(EyeClient):
    def exchange(self,p):
        old=list(self.output);state=super().exchange(p)
        if p[:2]==b'NH':
            targets=struct.unpack_from('<22H',p,12)
            for c in (18,19,20):self.output[c]=old[c]+max(-5,min(5,targets[c]-old[c]))
            state['output_us']=list(self.output)
        return state
class Tests(unittest.TestCase):
    def test_default_no_network(self):
        with patch.object(sys,'argv',['probe','common']),patch.object(probe,'Client') as client,contextlib.redirect_stdout(io.StringIO()):
            probe.main();client.assert_not_called()
    def test_joint_bases_reach_endpoints_and_stop(self):
        for basis,span in (('common',400),('differential',50),('left_only',400),('right_only',400)):
            with self.subTest(basis=basis),tempfile.TemporaryDirectory() as directory:
                root=Path(directory);(root/'build').mkdir();(root/'config').mkdir()
                profile=dict(pair_first_output_no_abnormal_operator_confirmed=True,pair_reference_us=[1500,1500],pair_common_requested_limits_us=[1100,1900],pair_left_only_requested_limits_us=[1100,1900],pair_right_only_requested_limits_us=[1100,1900])
                (root/'config/neck_follow.json').write_text(json.dumps(profile))
                SlewClient.instances=[]
                with patch.object(sys,'argv',['probe',basis,'--span-us',str(span),'--run','--operator-ready','--head-supported']),\
                     patch.object(probe,'ROOT',root),patch.object(probe,'Client',SlewClient),\
                     patch.object(probe.time,'sleep'),contextlib.redirect_stdout(io.StringIO()):probe.main()
                result=json.loads(next((root/'build').glob('neck_pair*.json')).read_text(encoding='utf-8'))
                self.assertTrue(result['digital_checks_passed']);self.assertEqual(result['digital_endpoints_us'],result['points_us'])
                self.assertEqual(result['final']['active_mask'],0);self.assertFalse(result['pair_mixing_verified'])
                for p in SlewClient.instances[-1].packets:
                    if p[:2]!=b'NH':continue
                    self.assertEqual(int.from_bytes(p[8:12],'little'),7<<18)
                    u=struct.unpack_from('<22H',p,12)
                    self.assertTrue(all(v==0 for v in u[:18]));self.assertEqual(u[18],1500)
                    if basis=='left_only':self.assertEqual(u[20],1500)
                    elif basis=='right_only':self.assertEqual(u[19],1500)
                    else:self.assertEqual(u[20],u[19] if basis=='common' else 3000-u[19])
    def test_common_request_cannot_authorize_broad_differential_test(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);(root/'config').mkdir()
            (root/'config/neck_follow.json').write_text(json.dumps(dict(pair_first_output_no_abnormal_operator_confirmed=True,
                pair_reference_us=[1500,1500],pair_common_requested_limits_us=[1100,1900])))
            with patch.object(sys,'argv',['probe','differential','--span-us','400','--run','--operator-ready','--head-supported']),\
                 patch.object(probe,'ROOT',root),patch.object(probe,'Client') as client:
                with self.assertRaisesRegex(ValueError,'exact coupled basis'):probe.main()
                client.assert_not_called()
    def test_no_observation_blocks_motion_before_network(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);(root/'config').mkdir();(root/'config/neck_follow.json').write_text('{}')
            with patch.object(sys,'argv',['probe','common','--run','--operator-ready','--head-supported']),\
                 patch.object(probe,'ROOT',root),patch.object(probe,'Client') as client:
                with self.assertRaisesRegex(ValueError,'no-abnormal'):probe.main()
                client.assert_not_called()
if __name__=='__main__':unittest.main(verbosity=2)