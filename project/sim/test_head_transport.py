import copy,socket,struct,sys,unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src/pc'))
from nh22 import motion,stop
from head_transport import HeadClient
import neck_transport as base
class Sock:
    def __init__(self,items):self.items=list(items);self.sent=[]
    def sendto(self,p,peer):self.sent.append(p)
    def settimeout(self,t):pass
    def recvfrom(self,_):
        item=self.items.pop(0)
        if isinstance(item,BaseException):raise item
        return item,('192.168.10.20',5005)
class Tests(unittest.TestCase):
    def client(self,items):
        c=HeadClient.__new__(HeadClient);c.reply_timeout=.06;c.discarded_replies=0;c.query_recoveries=0;c.confirmed_motion_retries=0;c.stop_query_recoveries=0
        c.peer=('192.168.10.20',5005);c.sock=Sock(items);return c
    def state(self,seq=101,query=False,**kwargs):
        return dict(dict(sequence=seq,query=query,have_sequence=True,echo_ms=10000,status=5,active_mask=3|(7<<18),configured_mask=3|(7<<18)),**kwargs)
    def packet(self):return motion(101,3|(7<<18),[1500]*22)
    def run_exchange(self,c,packet,states):
        with patch.object(base.time,'monotonic',return_value=10),patch.object(base,'decode_telemetry',side_effect=lambda index:states[index]):return c.exchange(packet)
    def test_lost_ack_queries_without_repeating_accepted_motion(self):
        c=self.client([socket.timeout(),0]);r=self.run_exchange(c,self.packet(),[self.state(query=True)])
        self.assertTrue(r['ack_recovered_by_query']);self.assertEqual([p[:2] for p in c.sock.sent],[b'NH',b'NQ'])
    def test_unaccepted_motion_retries_same_absolute_packet_once(self):
        c=self.client([socket.timeout(),0,1]);p=self.packet()
        r=self.run_exchange(c,p,[self.state(seq=100,query=True),self.state()])
        self.assertTrue(r['motion_retried_after_query']);self.assertEqual(c.sock.sent[0],c.sock.sent[2]);self.assertEqual(c.confirmed_motion_retries,1)
    def test_retry_lost_ack_is_verified_by_one_final_query(self):
        c=self.client([socket.timeout(),0,socket.timeout(),1])
        r=self.run_exchange(c,self.packet(),[self.state(seq=100,query=True),self.state(query=True)])
        self.assertTrue(r['motion_retry_confirmed_by_query']);self.assertEqual([p[:2] for p in c.sock.sent],[b'NH',b'NQ',b'NH',b'NQ'])
    def test_retry_exhaustion_does_not_loop_or_send_stop(self):
        c=self.client([socket.timeout(),0,socket.timeout(),1])
        with self.assertRaises(socket.timeout):self.run_exchange(c,self.packet(),[self.state(seq=100,query=True),self.state(seq=100,query=True)])
        self.assertEqual([p[:2] for p in c.sock.sent],[b'NH',b'NQ',b'NH',b'NQ'])
    def test_fault_or_other_sender_blocks_retry(self):
        for state in (self.state(seq=102,query=True),self.state(seq=100,query=True,status=3)):
            c=self.client([socket.timeout(),0])
            with self.assertRaises(socket.timeout):self.run_exchange(c,self.packet(),[state])
            self.assertEqual([p[:2] for p in c.sock.sent],[b'NH',b'NQ'])
    def test_query_timeout_never_blindly_retries(self):
        c=self.client([socket.timeout(),socket.timeout()])
        with self.assertRaises(socket.timeout):self.run_exchange(c,self.packet(),[])
        self.assertEqual([p[:2] for p in c.sock.sent],[b'NH',b'NQ'])
    def test_stop_is_not_repeated_when_query_proves_idle(self):
        c=self.client([socket.timeout(),0]);r=self.run_exchange(c,stop(101),[self.state(seq=100,query=True,status=0,active_mask=0)])
        self.assertTrue(r['stop_confirmed_by_query']);self.assertEqual([p[:2] for p in c.sock.sent],[b'NS',b'NQ'])
if __name__=='__main__':unittest.main(verbosity=2)