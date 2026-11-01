import struct,sys,unittest,socket
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src/pc'))
from nh22 import query,stop
import neck_transport as transport
class Sock:
    def __init__(self,rows):self.rows=list(rows);self.sent=[]
    def sendto(self,p,peer):self.sent.append(p)
    def settimeout(self,t):self.timeout=t
    def recvfrom(self,_):
        item=self.rows.pop(0)
        if isinstance(item,BaseException):raise item
        return item,('192.168.10.20',5005)
class Tests(unittest.TestCase):
    def client(self,states):
        c=transport.NeckClient.__new__(transport.NeckClient);c.reply_timeout=.1;c.discarded_replies=0
        c.peer=('192.168.10.20',5005);c.sock=Sock(list(range(len(states))))
        return c
    def test_old_motion_reply_cannot_acknowledge_stop(self):
        states=[dict(sequence=100,query=False,have_sequence=True,active_mask=7<<18),
                dict(sequence=101,query=False,have_sequence=True,active_mask=0)]
        c=self.client(states)
        with patch.object(transport,'decode_telemetry',side_effect=lambda b:states[b]):s=c.exchange(stop(101))
        self.assertEqual(s['active_mask'],0);self.assertEqual(c.discarded_replies,1);self.assertEqual(len(c.sock.sent),1)
    def test_query_requires_its_echo_and_query_flag(self):
        states=[dict(sequence=100,query=False,echo_ms=55),dict(sequence=100,query=True,echo_ms=44),dict(sequence=101,query=True,echo_ms=55)]
        c=self.client(states)
        with patch.object(transport,'decode_telemetry',side_effect=lambda b:states[b]):s=c.exchange(query(timestamp=55))
        self.assertEqual(s['sequence'],101);self.assertEqual(c.discarded_replies,2)
    def test_newer_sequence_detects_another_controller(self):
        states=[dict(sequence=103,query=False,have_sequence=True)];c=self.client(states)
        with patch.object(transport,'decode_telemetry',side_effect=lambda b:states[b]):
            with self.assertRaisesRegex(RuntimeError,'another sender'):c.exchange(stop(101))
    def test_wraparound_older_reply_is_discarded(self):
        states=[dict(sequence=0xffffffff,query=False,have_sequence=True),dict(sequence=1,query=False,have_sequence=True)]
        c=self.client(states)
        with patch.object(transport,'decode_telemetry',side_effect=lambda b:states[b]):s=c.exchange(stop(1))
        self.assertEqual(s['sequence'],1);self.assertEqual(c.discarded_replies,1)
    def test_lost_ack_is_confirmed_by_query_without_repeating_motion(self):
        c=self.client([]);c.sock=Sock([socket.timeout('lost ack'),0])
        state=dict(sequence=101,query=True,have_sequence=True,echo_ms=10000,status=0,active_mask=0)
        with patch.object(transport.time,'monotonic',return_value=10),patch.object(transport,'decode_telemetry',return_value=state):
            result=c.exchange(stop(101))
        self.assertTrue(result['ack_recovered_by_query'])
        self.assertEqual([p[:2] for p in c.sock.sent],[b'NS',b'NQ'])
    def test_missing_acceptance_is_not_treated_as_success(self):
        c=self.client([]);c.sock=Sock([socket.timeout('lost packet'),0])
        state=dict(sequence=100,query=True,have_sequence=True,echo_ms=10000,status=0,active_mask=0)
        with patch.object(transport.time,'monotonic',return_value=10),patch.object(transport,'decode_telemetry',return_value=state):
            with self.assertRaises(socket.timeout):c.exchange(stop(101))
        self.assertEqual([p[:2] for p in c.sock.sent],[b'NS',b'NQ'])
if __name__=='__main__':unittest.main(verbosity=2)