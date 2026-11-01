"""Bounded head motion recovery: query acceptance before one identical NH retry."""
import socket,struct,time
from neck_transport import NeckClient
from nh22 import query
class HeadClient(NeckClient):
    def __init__(self,*args,timeout=.06,**kwargs):
        self.confirmed_motion_retries=0;self.stop_query_recoveries=0
        super().__init__(*args,timeout=min(.06,timeout),**kwargs)
    def _query_state(self):return super().exchange(query(timestamp=int(time.monotonic()*1000)))
    def exchange(self,packet):
        kind=packet[:2]
        if kind not in (b'NH',b'NS'):return super().exchange(packet)
        expected=struct.unpack_from('<I',packet,4)[0]
        self.sock.sendto(packet,self.peer)
        try:return self._receive_match(False,expected)
        except socket.timeout:pass
        state=self._query_state()
        if kind==b'NS':
            if not state.get('status') and not state.get('active_mask'):
                self.stop_query_recoveries+=1;state['stop_confirmed_by_query']=True;return state
            raise socket.timeout('Stop acknowledgement missing; query did not confirm idle')
        if state.get('have_sequence') and state['sequence']==expected:
            self.query_recoveries+=1;state['ack_recovered_by_query']=True;return state
        mask=struct.unpack_from('<I',packet,8)[0]
        previous=(expected-1)&0xffffffff
        if (not state.get('have_sequence') or state.get('sequence')!=previous or state.get('status',0)&2
                or state.get('active_mask',0)&~mask or state.get('configured_mask',0)&mask!=mask):
            raise socket.timeout('Motion acceptance not confirmed; retry blocked by board state')
        # Query proves this sequence has not been accepted. Reuse precisely the
        # same absolute target/mask/sequence; a delayed duplicate is idempotent.
        self.confirmed_motion_retries+=1;self.sock.sendto(packet,self.peer)
        try:
            result=self._receive_match(False,expected);result['motion_retried_after_query']=True;return result
        except socket.timeout:
            state=self._query_state()
            if state.get('have_sequence') and state['sequence']==expected:
                self.query_recoveries+=1;state['motion_retry_confirmed_by_query']=True;return state
            raise socket.timeout('One confirmed motion retry exhausted; hold policy applies')