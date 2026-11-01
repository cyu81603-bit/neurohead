import json,struct,subprocess,sys,unittest
from pathlib import Path
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1];sys.path[:0]=[str(ROOT/'src/pc'),str(ROOT/'sim')]
import nh22
from face_commission import FaceCommissionControl,FACE_CHANNELS
from head_control import MASK
from test_face_commission import plan,Board
from test_head_control import profile,Lock
class ExtensionTests(unittest.TestCase):
    def test_wire_version_lengths_and_jaw_value_and_timestamp(self):
        pulses=[1500]*22;pulses[21]=1670;p=nh22.motion(9,1<<21,pulses,0x12345678)
        self.assertEqual(p[2],3);self.assertEqual(len(p),62);self.assertEqual(struct.unpack_from('<H',p,54)[0],1670);self.assertEqual(struct.unpack_from('<I',p,56)[0],0x12345678)
        self.assertEqual(nh22.config(8,21,1450,1550,1500,1,False)[8],21)
        with self.assertRaises(ValueError):nh22.motion(1,1<<22,pulses)
    def test_telemetry_last_output_and_old_wire_rejection(self):
        targets=[1500]*22;outputs=[1500]*22;targets[-1]=1670;outputs[-1]=1632
        data=nh22.seal(b'NT\x03\x06'+struct.pack('<9I',9,0,0,0,0,0,0,0,77)+struct.pack('<22H',*targets)+struct.pack('<22H',*outputs))
        r=nh22.decode_telemetry(data);self.assertEqual(len(data),130);self.assertEqual(r['output_us'][21],1632)
        old=nh22.seal(b'NT\x02\x06'+struct.pack('<9I',9,0,0,0,0,0,0,0,77)+struct.pack('<42H',*([1500]*42)))
        with self.assertRaises(ValueError):nh22.decode_telemetry(old)
        legacy=nh22.seal(b'NH\x02\0'+struct.pack('<II21HI',1,1<<20,*([1500]*21),0))
        path=ROOT/'build/verification/legacy21_packet.bin';path.write_bytes(legacy)
        result=subprocess.check_output([str(ROOT/'build/verification/protocol_test.exe'),str(path)]);self.assertEqual(result.strip(),b'0')
    def test_original_pins_unchanged_and_jaw_independent(self):
        new=json.loads((ROOT/'config/channels.json').read_text(encoding='utf-8'))['channels']
        old=json.loads((ROOT/'reference/legacy21_channels.json').read_text(encoding='utf-8'))['channels']
        for a,b in zip(new[:21],old):self.assertEqual((a['channel'],a['signal_pin'],a['package_pin']),(b['channel'],b['signal_pin'],b['package_pin']))
        self.assertEqual((new[21]['signal_pin'],new[21]['package_pin']),(24,'T14'));self.assertFalse(new[21]['enabled'])
    def test_jaw_can_only_be_single_short_explicit_trial_until_observed(self):
        Board.instances=[];Board.fail=False;clock=[0.]
        c=FaceCommissionControl(dict(profile(),face_channels=plan()),clock=lambda:clock[0],client_factory=Board,lock_factory=lambda _:Lock());c._guard=lambda:None
        with patch('eye_follow_panel.verified_command',return_value=[]):c.start()
        try:
            self.assertIn(21,FACE_CHANNELS)
            with self.assertRaises(ValueError):c.begin_face_trial(21,1510,True,False,True)
            c.begin_face_trial(21,1500,True,False,True);c.tick(.05);self.assertEqual(c.last_state['active_mask'],MASK|(1<<21))
            self.assertEqual(c.last_state['output_us'][21],1500);clock[0]=.21;c.tick(.05);self.assertEqual(c.last_state['active_mask'],MASK)
            c.record_face_observation(21,'neutral');self.assertTrue(c.records[-1]['mounted_neutral_verified']);self.assertEqual(c.records[-1]['joint'],'jaw')
        finally:c.end(True)
    def test_imported_eye_evidence_hashes_remain_guarded(self):
        from eye_follow_panel import verified_command
        verified_command('both',False,False)
if __name__=='__main__':unittest.main(verbosity=2)
