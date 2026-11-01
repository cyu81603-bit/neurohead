"""Correlate neck UDP replies; late packets must not acknowledge newer commands."""
import socket,struct,time
from nh22 import Client,decode_telemetry,query
class NeckClient(Client):
    def __init__(self,*args,timeout=.15,**kwargs):
        self.reply_timeout=timeout;self.discarded_replies=0;self.query_recoveries=0
        super().__init__(*args,timeout=timeout,**kwargs)
    def exchange(self,packet):
        is_query=packet[:2]==b'NQ'
        expected=struct.unpack_from('<I',packet,6 if is_query else 4)[0]
        self.sock.sendto(packet,self.peer)
        try:return self._receive_match(is_query,expected)
        except socket.timeout:
            if is_query:raise
            original_error=socket.timeout('command acknowledgement missing and acceptance not confirmed')
            state=self.exchange(query(timestamp=int(time.monotonic()*1000)))
            if state.get('have_sequence') and state['sequence']==expected:
                self.query_recoveries=getattr(self,'query_recoveries',0)+1
                state['ack_recovered_by_query']=True;return state
            raise original_error
    def _receive_match(self,is_query,expected):
        deadline=time.monotonic()+self.reply_timeout
        while True:
            remaining=deadline-time.monotonic()
            if remaining<=0:raise socket.timeout('no matching board acknowledgement before deadline')
            self.sock.settimeout(remaining)
            data,peer=self.sock.recvfrom(2048)
            if peer!=self.peer:self.discarded_replies+=1;continue
            try:state=decode_telemetry(data)
            except ValueError:self.discarded_replies+=1;continue
            if is_query:
                if state.get('query') and state.get('echo_ms')==expected:return state
            elif not state.get('query'):
                sequence=state['sequence']
                if sequence==expected:return state
                if state.get('have_sequence') and 0<((sequence-expected)&0xffffffff)<0x80000000:
                    raise RuntimeError('board sequence advanced beyond this controller; another sender may own it')
            self.discarded_replies+=1