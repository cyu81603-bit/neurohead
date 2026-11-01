import contextlib,io,sys,unittest
from pathlib import Path
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"src/pc"));sys.path.insert(0,str(ROOT/"sim"))
import bench_mg90s
from test_eye_span import FakeClient
class Busy(FakeClient):
    def __init__(self,**kwargs):super().__init__(**kwargs);self.active=1
class Tests(unittest.TestCase):
    def args(self):return ["bench","--run","--unloaded","--channel","1","--known-project-pattern"]
    def test_busy_preflight_does_not_stop_other_controller(self):
        Busy.instances=[]
        with patch.object(sys,"argv",self.args()),patch.object(bench_mg90s,"Client",Busy),patch.object(bench_mg90s,"acquire_run_lock",return_value=contextlib.nullcontext()),contextlib.redirect_stdout(io.StringIO()):
            with self.assertRaisesRegex(RuntimeError,"no actuator writes"):bench_mg90s.main()
        self.assertEqual([p[:2] for p in Busy.instances[-1].packets],[b"NQ"])
    def test_lock_contention_never_connects_client(self):
        with patch.object(sys,"argv",self.args()),patch.object(bench_mg90s,"Client") as client,patch.object(bench_mg90s,"acquire_run_lock",side_effect=RuntimeError("another controller")):
            with self.assertRaisesRegex(RuntimeError,"another controller"):bench_mg90s.main()
        client.assert_not_called()
if __name__=="__main__":unittest.main(verbosity=2)
