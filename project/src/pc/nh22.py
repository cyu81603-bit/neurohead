"""NH22 v3 codec and client. Stdlib only. CLI motion defaults to dry-run."""
import argparse,binascii,json,socket,struct,time
from pathlib import Path
N=22
MASK=(1<<N)-1

def crc(data):
    return binascii.crc_hqx(data,0xffff)
def seal(data):
    return data+struct.pack("<H",crc(data))
def header(kind,seq):
    return b"N"+kind.encode()+bytes((3,0))+struct.pack("<I",seq&0xffffffff)
def query(seq=0,timestamp=0):
    return seal(b"NQ"+bytes((3,0))+struct.pack("<HI",seq&0xffff,timestamp&0xffffffff))
def stop(seq):
    return seal(header("S",seq))
def config(seq,ch,lo,hi,neutral,step,hold):
    if not (0<=ch<N and 600<=lo<=neutral<=hi<=2400 and 1<=step<=100):
        raise ValueError("invalid calibration")
    return seal(header("C",seq)+struct.pack("<BBHHHH",ch,int(hold),lo,hi,neutral,step))
def motion(seq,mask,pulses,timestamp=0):
    if len(pulses)!=N or not mask or mask&~MASK:
        raise ValueError("invalid channel mask/count")
    if any(not 600<=pulses[i]<=2400 for i in range(N) if mask&(1<<i)):
        raise ValueError("invalid pulse")
    return seal(header("H",seq)+struct.pack("<I22HI",mask,*pulses,timestamp&0xffffffff))
def decode_telemetry(data):
    if len(data)!=130 or data[:3]!=b"NT\x03" or data[3]&~7 or crc(data[:-2])!=struct.unpack_from("<H",data,128)[0]:
        raise ValueError("invalid v3 telemetry (old two-channel firmware is incompatible)")
    names=("sequence","status","active_mask","configured_mask","accepted","invalid","stale","watchdog_events","echo_ms")
    result=dict(zip(names,struct.unpack_from("<9I",data,4)))
    result.update(have_sequence=bool(data[3]&4),query=bool(data[3]&2),
                  target_us=list(struct.unpack_from("<22H",data,40)),
                  output_us=list(struct.unpack_from("<22H",data,84)))
    return result

def load_profile(path):
    value=json.loads(Path(path).read_text(encoding="utf-8-sig"))
    rows=value["channels"]
    if len(rows)!=N or [r["channel"] for r in rows]!=list(range(N)):
        raise ValueError("profile must contain unique ordered channels 0..20")
    if len({r["id"] for r in rows})!=N:
        raise ValueError("duplicate logical id")
    for r in rows:
        if r.get("enabled"):
            if not r.get("mechanical_verified") or not r.get("joint"):
                raise ValueError("enabled channel lacks joint/mechanical verification: "+r["id"])
            if any(type(r.get(k)) is not int for k in ("min_us","max_us","neutral_us","step_us")):
                raise ValueError("missing integer calibration: "+r["id"])
            config(0,r["channel"],r["min_us"],r["max_us"],r["neutral_us"],r["step_us"],r.get("hold_on_timeout",False))
    return rows

class Client:
    def __init__(self,host="192.168.10.20",port=5005,bind=None,timeout=1):
        self.peer=(socket.gethostbyname(host),port)
        self.sock=socket.socket(socket.AF_INET,socket.SOCK_DGRAM)
        self.sock.settimeout(timeout)
        if bind:
            from board_network import bind_board_socket
            bind_board_socket(self.sock,bind)
        state=self.exchange(query(timestamp=int(time.monotonic()*1000)))
        self.sequence=(state["sequence"]+1)&0xffffffff if state["have_sequence"] else 1
    def exchange(self,packet):
        self.sock.sendto(packet,self.peer)
        data,peer=self.sock.recvfrom(2048)
        if peer!=self.peer:raise ValueError("unexpected telemetry peer")
        return decode_telemetry(data)
    def next_sequence(self):
        result=self.sequence
        self.sequence=(result+1)&0xffffffff
        return result
    def close(self):
        self.sock.close()

def assert_motion_ready(rows,mask):
    for row in rows:
        if mask&(1<<row['channel']) and row.get('legacy_guard'):
            old=json.loads(Path(row['legacy_guard']).read_text(encoding='utf-8-sig'))
            if old.get('motion_inhibited',True):
                raise ValueError('Original eye calibration remains inhibited; complete its mechanical verification first')

def prepare_pose(rows,assignments):
    by_id={r["id"]:r for r in rows}
    pulses=[0]*N
    mask=0
    for item in assignments:
        name,text=item.split("=",1)
        if name not in by_id:raise ValueError("unknown joint id "+name)
        r=by_id[name]
        if not r.get("enabled") or not r.get("mechanical_verified"):
            raise ValueError("channel not calibrated/enabled: "+name)
        v=int(text)
        if not r["min_us"]<=v<=r["max_us"]:raise ValueError("outside mechanical range: "+name)
        if mask&(1<<r["channel"]):raise ValueError("duplicate joint assignment")
        mask|=1<<r["channel"];pulses[r["channel"]]=v
    motion(1,mask,pulses)
    return mask,pulses

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("action",choices=("query","configure","pose","stop"))
    p.add_argument("--host",default="192.168.10.20")
    p.add_argument("--port",default=5005,type=int)
    p.add_argument("--bind")
    p.add_argument("--profile",default=str(Path(__file__).resolve().parents[2]/"config/channels.json"))
    p.add_argument("--values",nargs="*",default=[])
    p.add_argument("--duration",type=float,default=1)
    p.add_argument("--execute",action="store_true",help="explicitly send config/pose/stop; otherwise dry-run")
    a=p.parse_args()
    rows=load_profile(a.profile)
    if a.action=="pose":
        if not 0<a.duration<=10:p.error("duration must be 0..10 seconds")
        mask,pulses=prepare_pose(rows,a.values)
        if not a.execute:
            print(json.dumps({"dry_run":True,"mask":mask,"pulse_us":pulses,"frame_hex":motion(1,mask,pulses).hex()}))
            return
    elif a.action=="configure" and not a.execute:
        print(json.dumps({"dry_run":True,"configured_ids":[r["id"] for r in rows if r.get("enabled")]}))
        return
    elif a.action=="stop" and not a.execute:
        print(json.dumps({"dry_run":True,"action":"disable all PWM; support loaded neck before use"}))
        return
    if a.action=='pose':assert_motion_ready(rows,mask)
    client=Client(a.host,a.port,a.bind)
    try:
        if a.action=="query":
            print(json.dumps(client.exchange(query(timestamp=int(time.monotonic()*1000))),indent=2));return
        if a.action=="stop":
            print(json.dumps(client.exchange(stop(client.next_sequence())),indent=2));return
        if a.action=="configure":
            state=client.exchange(query())
            if state["status"]&7:raise RuntimeError("board must be disarmed and fault-free before configuration")
            enabled=[r for r in rows if r.get("enabled")]
            if not enabled:raise ValueError("no enabled calibrated channels in profile")
            for r in enabled:
                seq=client.next_sequence()
                state=client.exchange(config(seq,r["channel"],r["min_us"],r["max_us"],r["neutral_us"],r["step_us"],r.get("hold_on_timeout",False)))
                if state["sequence"]!=seq or not state["configured_mask"]&(1<<r["channel"]):
                    raise RuntimeError("calibration rejected")
            print(json.dumps(state,indent=2));return
        # Hold only the requested channels. Omitted channels are disabled at the next frame.
        start=time.monotonic()
        try:
            while time.monotonic()-start<a.duration:
                before=time.monotonic()
                seq=client.next_sequence()
                state=client.exchange(motion(seq,mask,pulses,int(before*1000)))
                if state["sequence"]!=seq or state["status"]&2:
                    raise RuntimeError("motion rejected or watchdog fault")
                time.sleep(max(0,0.02-(time.monotonic()-before)))
        finally:
            # Do not drop a loaded neck: configured hold-mask channels freeze on watchdog.
            # Face channels default to PWM disable. Use explicit stop only with support.
            print("Command stream ended; per-channel watchdog policy applies after 300 ms.")
        print(json.dumps(state,indent=2))
    finally:
        client.close()
if __name__=="__main__":
    main()
