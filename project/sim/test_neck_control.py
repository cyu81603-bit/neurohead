import sys,unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src/pc'));sys.path.insert(0,str(ROOT/'sim'))
from neck_control import NeckControl
from test_vertical_feedback import EyeClient
class Lock:
    closed=False
    def close(self):self.closed=True
class Client(EyeClient):
    fail=False
    def exchange(self,p):
        if self.fail and p[:2]==b'NH':self.packets.append(p);raise RuntimeError('transport failure')
        return super().exchange(p)
class Busy(Client):
    def __init__(self,**kwargs):super().__init__(**kwargs);self.active=1<<18
class Tests(unittest.TestCase):
    def control(self,client=Client):
        Client.fail=False;client.instances=[]
        p=dict(yaw_reference_operator_verified=True,left_rod_positive_is_up=True,
            right_rod_positive_is_up=True,pair_first_output_no_abnormal_operator_confirmed=True)
        return NeckControl(p,client_factory=client,lock_factory=lambda _:Lock())
    def test_open_idle_does_not_connect(self):
        c=self.control();c.tick(.05);self.assertFalse(Client.instances)
    def test_slew_only_neck_hold_configuration_and_supported_end(self):
        c=self.control();c.start();c.set_targets([1900,1900,1100]);c.tick(.05)
        self.assertEqual(c.output,[1505,1505,1495]);packets=Client.instances[-1].packets
        self.assertTrue(all(p[9]==1 for p in packets if p[:2]==b'NC'))
        import struct
        moves=[p for p in packets if p[:2]==b'NH']
        self.assertTrue(all(int.from_bytes(p[8:12],'little')==7<<18 for p in moves))
        self.assertTrue(all(all(v==0 for v in struct.unpack_from('<22H',p,12)[:18]) for p in moves))
        with self.assertRaises(ValueError):c.end()
        c.end(True);self.assertEqual(c.mode,'idle');self.assertEqual(packets[-1][:2],b'NS')
    def test_pause_holds_output_and_resume_uses_staged_target(self):
        c=self.control();c.start();c.set_targets([1900]*3);c.tick(.05);c.pause()
        held=list(c.output);c.set_targets([1100]*3)
        for _ in range(10):c.tick(.05)
        self.assertEqual(c.output,held);self.assertEqual(c.mode,'paused')
        c.start();c.tick(.05);self.assertEqual(c.output,[u-5 for u in held]);c.end(True)
    def test_transport_fault_does_not_disable_loaded_neck(self):
        c=self.control();c.start();c.tick(.05);Client.fail=True;c.tick(.05)
        self.assertEqual(c.mode,'fault');packets=Client.instances[-1].packets
        self.assertFalse(any(p[:2]==b'NS' for p in packets))
        Client.fail=False;c.end(True);self.assertEqual(c.mode,'idle')
    def test_busy_board_is_not_stopped(self):
        c=self.control(Busy)
        with self.assertRaisesRegex(RuntimeError,'occupied'):c.start()
        self.assertEqual([p[:2] for p in Busy.instances[-1].packets],[b'NQ'])
        self.assertEqual(c.mode,'idle');self.assertIsNone(c.client)
    def test_outside_envelope_rejected(self):
        c=self.control()
        with self.assertRaises(ValueError):c.set_targets([1000,1500,1500])
    def test_difference_cycle_returns_to_neutral_and_keeps_holding(self):
        c=self.control();c.start()
        for target in ([1500]*3,[1500,1900,1100],[1500]*3,[1500,1100,1900],[1500]*3):
            c.set_targets(target)
            for _ in range(120):c.tick(.05)
            self.assertEqual(c.output,list(target));self.assertEqual(c.mode,'running')
        c.pause()
        for _ in range(40):c.tick(.05)
        self.assertEqual(c.output,[1500]*3);self.assertEqual(c.mode,'paused')
        self.assertEqual(c.last_state['active_mask'],7<<18)
        self.assertFalse(any(p[:2]==b'NS' for p in Client.instances[-1].packets))
        c.end(True);self.assertEqual(c.last_state['active_mask'],0)
    def test_end_recovers_if_board_already_stopped_after_lost_reply(self):
        c=self.control();c.start();c.tick(.05)
        Client.instances[-1].active=0;c.mode='fault';c.error='previous stop not acknowledged'
        c.end(True)
        self.assertEqual(c.mode,'idle');self.assertEqual(c.error,'');self.assertIsNone(c.client)
        self.assertFalse(any(p[:2]==b'NS' for p in Client.instances[-1].packets))
    def test_calibrated_neutral_config_and_first_frame_use_1270(self):
        base=self.control();p=dict(base.profile,manual_neck_reference_us=[1500,1270,1500])
        c=NeckControl(p,client_factory=Client,lock_factory=lambda _:Lock())
        self.assertEqual(c.desired,[1500,1270,1500]);c.start();c.tick(.05)
        configs=[p for p in Client.instances[-1].packets if p[:2]==b'NC']
        self.assertEqual([int.from_bytes(p[14:16],'little') for p in configs],[1500,1270,1500])
        self.assertEqual(c.output,[1500,1270,1500]);c.end(True)
if __name__=='__main__':unittest.main(verbosity=2)