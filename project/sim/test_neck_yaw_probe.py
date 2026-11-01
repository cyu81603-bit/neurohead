import contextlib,io,json,struct,sys,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src/pc'));sys.path.insert(0,str(ROOT/'sim'))
import neck_yaw_probe as probe
from test_vertical_feedback import EyeClient
class SlewClient(EyeClient):
    fail=False
    def __init__(self,**kwargs):super().__init__(**kwargs);self.count=0
    def exchange(self,p):
        old=self.output[18];state=super().exchange(p)
        if p[:2]==b'NH':
            target=struct.unpack_from('<22H',p,12)[18]
            self.output[18]=old+max(-5,min(5,target-old))
            state['output_us']=list(self.output);self.count+=1
            if self.fail and self.count==3:raise RuntimeError('injected failure')
        return state
class BusyClient(SlewClient):
    def __init__(self,**kwargs):super().__init__(**kwargs);self.active=1<<18
class Tests(unittest.TestCase):
    def test_default_no_network(self):
        with patch.object(sys,'argv',['probe']),patch.object(probe,'Client') as client,contextlib.redirect_stdout(io.StringIO()):
            probe.main();client.assert_not_called()
    def session(self,client):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);(root/'config').mkdir();(root/'build').mkdir()
            (root/'config/neck_follow.json').write_text(json.dumps(dict(yaw_signal_wiring_operator_confirmed=True,
                loaded_yaw_probe_requested_limits_us=[1100,1900],loaded_first_pulse_digital_checks_passed=True)))
            client.instances=[]
            with patch.object(sys,'argv',['probe','--run','--operator-ready','--head-supported']),\
                 patch.object(probe,'ROOT',root),patch.object(probe,'Client',client),\
                 patch.object(probe.time,'sleep'),contextlib.redirect_stdout(io.StringIO()):
                if client is BusyClient or client.fail:
                    with self.assertRaises(RuntimeError):probe.main()
                else:probe.main()
            files=list((root/'build').glob('neck_yaw_probe*.json'))
            return client.instances[-1].packets,json.loads(files[0].read_text(encoding='utf-8')) if files else None
    def test_slew_reaches_both_endpoints_only_yaw_and_stops(self):
        SlewClient.fail=False;packets,result=self.session(SlewClient)
        self.assertEqual(result['digital_endpoints_us'],[1500,1100,1500,1900,1500])
        self.assertEqual(result['planned_duration_s'],19)
        self.assertTrue(result['digital_checks_passed'])
        self.assertEqual(result['final']['active_mask'],0)
        for p in packets:
            if p[:2]==b'NH':
                self.assertEqual(int.from_bytes(p[8:12],'little'),1<<18)
                self.assertTrue(all(v==0 for i,v in enumerate(struct.unpack_from('<22H',p,12)) if i!=18))
        self.assertEqual([p[:2] for p in packets[-2:]],[b'NS',b'NC'])
    def test_busy_controller_never_receives_stop(self):
        BusyClient.fail=False;packets,result=self.session(BusyClient)
        self.assertEqual([p[:2] for p in packets],[b'NQ']);self.assertIsNone(result)
    def test_runtime_failure_still_stops_and_does_not_claim_pass(self):
        SlewClient.fail=True
        try:
            packets,result=self.session(SlewClient)
            self.assertEqual([p[:2] for p in packets[-2:]],[b'NS',b'NC'])
            self.assertNotIn('digital_checks_passed',result)
            self.assertEqual(result['final']['active_mask'],0)
        finally:SlewClient.fail=False
if __name__=='__main__':unittest.main(verbosity=2)