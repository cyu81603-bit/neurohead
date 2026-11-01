import contextlib,io,json,struct,sys,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src/pc'));sys.path.insert(0,str(ROOT/'sim'))
import neck_pair_midpoint as pair
from test_vertical_feedback import EyeClient
class Busy(EyeClient):
    def __init__(self,**kwargs):super().__init__(**kwargs);self.active=1<<18
class Tests(unittest.TestCase):
    def test_default_no_network(self):
        with patch.object(sys,'argv',['pair']),patch.object(pair,'Client') as client,contextlib.redirect_stdout(io.StringIO()):
            pair.main();client.assert_not_called()
    def session(self,client):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);(root/'build').mkdir();(root/'config').mkdir()
            (root/'config/neck_follow.json').write_text(json.dumps(dict(yaw_reference_operator_verified=True,yaw_reference_pulse_us=1500)))
            client.instances=[]
            with patch.object(sys,'argv',['pair','--run','--operator-ready','--head-supported']),\
                 patch.object(pair,'ROOT',root),patch.object(pair,'Client',client),patch.object(pair.time,'sleep'),\
                 contextlib.redirect_stdout(io.StringIO()):
                if client is Busy:
                    with self.assertRaisesRegex(RuntimeError,'no actuator writes'):pair.main()
                else:pair.main()
            files=list((root/'build').glob('neck_pair_first*.json'))
            return client.instances[-1].packets,json.loads(files[0].read_text(encoding='utf-8')) if files else None
    def test_all_three_neck_channels_atomic_without_eyes_then_stop(self):
        packets,result=self.session(EyeClient)
        configs=[p for p in packets if p[:2]==b'NC'];commands=[p for p in packets if p[:2]==b'NH']
        self.assertEqual([p[8] for p in configs],[18,19,20]);self.assertEqual(len(commands),4)
        for p in commands:
            self.assertEqual(int.from_bytes(p[8:12],'little'),7<<18)
            self.assertEqual(list(struct.unpack_from('<22H',p,12)),[0]*18+[1500]*3)
        self.assertEqual(packets[-1][:2],b'NS')
        self.assertTrue(result['digital_checks_passed']);self.assertFalse(result['pair_mechanical_neutral_verified'])
        self.assertEqual(result['final']['active_mask'],0)
    def test_busy_neck_never_stopped_by_new_run(self):
        packets,result=self.session(Busy)
        self.assertEqual([p[:2] for p in packets],[b'NQ']);self.assertIsNone(result)
if __name__=='__main__':unittest.main(verbosity=2)