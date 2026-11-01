import sys,time,threading,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src/pc'))
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'sim'))
from neck_session import NeckSession
from test_vertical_feedback import EyeClient
class Lock:
    def close(self):pass
class FakeClient(EyeClient):
    def __init__(self,**kwargs):super().__init__(**kwargs);self.times=[];self.threads=[]
    def exchange(self,p):
        self.threads.append(threading.get_ident())
        if p[:2]==b'NH':self.times.append(time.monotonic())
        return super().exchange(p)
class Tests(unittest.TestCase):
    def test_heartbeat_continues_without_gui_polling_and_io_stays_on_worker(self):
        FakeClient.instances=[]
        s=NeckSession(dict(yaw_reference_operator_verified=True,pair_first_output_no_abnormal_operator_confirmed=True,
            manual_neck_reference_us=[1500,1270,1500]),client_factory=FakeClient,lock_factory=lambda _:Lock())
        try:
            self.assertIsNone(s.client);s.start();s.set_targets([1500,1350,1500])
            time.sleep(.45) # Simulate a blocked Tk/UI thread: no .tick calls.
            client=FakeClient.instances[-1]
            self.assertGreaterEqual(len(client.times),5)
            self.assertLess(max(b-a for a,b in zip(client.times,client.times[1:])),.25)
            self.assertEqual(len(set(client.threads)),1);self.assertNotEqual(client.threads[0],threading.get_ident())
            s.pause();held=s.output;time.sleep(.2);self.assertEqual(s.output,held)
            self.assertFalse(any(p[:2]==b'NS' for p in client.packets))
            s.end(True);self.assertEqual(s.mode,'idle')
        finally:
            if s.mode!='idle':s.end(True)
            s.close()
    def test_timed_out_late_start_does_not_emit_motion(self):
        class Slow(FakeClient):
            def __init__(self,**kwargs):time.sleep(2.2);super().__init__(**kwargs)
        Slow.instances=[]
        s=NeckSession(dict(yaw_reference_operator_verified=True,pair_first_output_no_abnormal_operator_confirmed=True),
            client_factory=Slow,lock_factory=lambda _:Lock())
        try:
            with self.assertRaisesRegex(RuntimeError,'timed out'):s.start()
            time.sleep(.35)
            self.assertEqual(s.mode,'idle')
            self.assertFalse(any(p[:2]==b'NH' for p in Slow.instances[-1].packets))
        finally:s.close()
if __name__=='__main__':unittest.main(verbosity=2)