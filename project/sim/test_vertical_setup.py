import contextlib,io,json,sys,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/"src/pc"));sys.path.insert(0,str(ROOT/"sim"))
import vertical_setup as vertical
from test_eye_span import FakeClient
class VerticalFake(FakeClient):
    def exchange(self,packet):
        result=super().exchange(packet)
        result["configured_mask"]=3
        if packet[:2]==b"NH":
            self.active=2;self.output=int.from_bytes(packet[14:16],"little")
            result.update(active_mask=2,output_us=[1500,self.output]+[1500]*19)
        return result
class Tests(unittest.TestCase):
    def test_neutral_and_sweep_bounds(self):
        values,ends=vertical.plan("neutral");self.assertEqual(len(values),40);self.assertEqual(set(values),{1500})
        for span in (25,50,100,150,200):
            values,ends=vertical.plan("sweep",span)
            self.assertEqual([values[i] for i in ends],[1500,1500+span,1500-span,1500])
            self.assertLessEqual(len(values)*.05,10)
    def test_missing_neutral_blocks_sweep_without_network(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/"profile.json";p.write_text(json.dumps({"channel":1,"assembled_at_1500_operator_confirmed":True}))
            with patch.object(sys,"argv",["v","sweep","--run","--operator-ready","--profile",str(p)]),patch.object(vertical,"Client") as client:
                with self.assertRaises(ValueError):vertical.main()
            client.assert_not_called()
    def test_loaded_neutral_uses_only_pin4_and_stops(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);(root/"build").mkdir();p=root/"profile.json"
            p.write_text(json.dumps({"channel":1,"assembled_at_1500_operator_confirmed":True}))
            out=root/"result.json";VerticalFake.instances=[];VerticalFake.fail_at=None
            with patch.object(sys,"argv",["v","neutral","--run","--operator-ready","--profile",str(p),"--out",str(out)]),patch.object(vertical,"ROOT",root),patch.object(vertical,"Client",VerticalFake),patch.object(vertical.time,"sleep"),contextlib.redirect_stdout(io.StringIO()):
                vertical.main()
            result=json.loads(out.read_text(encoding="utf-8"))
            self.assertTrue(result["digital_checks_passed"])
            self.assertEqual(result["final"]["active_mask"],0)
            packets=[p for p in VerticalFake.instances[-1].packets if p[:2]==b"NH"]
            self.assertEqual(len(packets),40)
            self.assertTrue(all(int.from_bytes(p[8:12],"little")==2 for p in packets))
if __name__=="__main__":unittest.main(verbosity=2)
