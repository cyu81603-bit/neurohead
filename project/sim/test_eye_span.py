import contextlib, hashlib, io, json, struct, sys, tempfile, time, unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"src/pc"))
import eye_span_trial as trial
class FakeClient:
    instances=[]
    fail_at=None
    def __init__(self,**kwargs):
        self.packets=[];self.seq=1;self.active=0;self.output=1500;self.count=0
        type(self).instances.append(self)
    def next_sequence(self):
        self.seq+=1;return self.seq
    def exchange(self,packet):
        self.packets.append(packet)
        kind=packet[:2]
        if kind==b"NH":
            self.count+=1
            if self.fail_at==self.count:raise RuntimeError("injected receive failure")
            self.active=1;self.output=struct.unpack_from("<H",packet,12)[0]
        elif kind==b"NS":self.active=0
        elif kind==b"NC":self.output=struct.unpack_from("<H",packet,14)[0]
        return {"sequence":self.seq,"status":5 if self.active else 0,
                "active_mask":self.active,"configured_mask":1,"output_us":[self.output]*22}
    def close(self):pass
class Tests(unittest.TestCase):
    def test_no_run_means_no_network(self):
        with patch.object(sys,"argv",["eye_span_trial.py"]),patch.object(trial,"Client") as client,contextlib.redirect_stdout(io.StringIO()):
            trial.main()
        client.assert_not_called()
    def session(self,d):
        guard=Path(d)/"guard.json";guard.write_text('{"motion_inhibited":true}')
        session=Path(d)/"session.json"
        value={"expires_epoch":time.time()+119,"confirmed_span_us":[1000,2000],
               "same_linkage_full_span_smooth_and_returned":True,
               "single_pin10_servo_powered_and_observable":True,
               "operator_report":"same linkage traversed span smoothly and returned",
               "guard_sha256":hashlib.sha256(guard.read_bytes()).hexdigest()}
        session.write_text(json.dumps(value))
        return guard,session,value
    def test_missing_physical_evidence_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            guard,session,value=self.session(d)
            value["same_linkage_full_span_smooth_and_returned"]=False
            with patch.object(trial,"GUARD",guard),self.assertRaises(ValueError):
                trial.validate_session(value,1000,2000)
    def test_active_pending_bits_allowed_one_use_stop_and_restore(self):
        with tempfile.TemporaryDirectory() as d:
            guard,session,value=self.session(d)
            FakeClient.fail_at=None
            with patch.object(trial,"GUARD",guard),patch.object(trial,"Client",FakeClient),patch.object(trial.time,"sleep"),contextlib.redirect_stdout(io.StringIO()):
                trial.run(session,1000,2000)
                with self.assertRaises(FileExistsError):trial.run(session,1000,2000)
            packets=FakeClient.instances[-1].packets
            self.assertEqual([p[:2] for p in packets[-2:]],[b"NS",b"NC"])
            result=json.loads(session.with_suffix(".result.json").read_text())
            self.assertTrue(result["digital_checks_passed"])
            self.assertEqual(result["motion_frames"],280)
            self.assertEqual(result["final"]["active_mask"],0)
    def test_motion_error_still_stops_and_restores(self):
        with tempfile.TemporaryDirectory() as d:
            guard,session,value=self.session(d)
            FakeClient.fail_at=2
            with patch.object(trial,"GUARD",guard),patch.object(trial,"Client",FakeClient),patch.object(trial.time,"sleep"),self.assertRaises(RuntimeError):
                trial.run(session,1000,2000)
            self.assertEqual([p[:2] for p in FakeClient.instances[-1].packets[-2:]],[b"NS",b"NC"])
            result=json.loads(session.with_suffix(".result.json").read_text())
            self.assertEqual(result["motion_frames"],1)
            self.assertNotIn("digital_checks_passed",result)
            FakeClient.fail_at=None
if __name__=="__main__":unittest.main(verbosity=2)
