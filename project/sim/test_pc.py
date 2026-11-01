import sys,struct,subprocess,tempfile,json,unittest,socket,threading
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"src/pc"))
import nh22
class ProtocolTests(unittest.TestCase):
 def c_kind(self,packet):
  with tempfile.NamedTemporaryFile(dir=ROOT/"build/verification",delete=False) as f:
   f.write(packet);path=Path(f.name)
  try:return int(subprocess.check_output([str(ROOT/"build/verification/protocol_test.exe"),str(path)]))
  finally:path.unlink()
 def test_cross_language(self):
  packets=[(nh22.query(7,123),1),(nh22.motion(0xffffffff,nh22.MASK,[1500]*22,123),2),
           (nh22.config(123,20,1490,1510,1500,2,True),3),(nh22.stop(5),4)]
  for frame,kind in packets:
   self.assertEqual(self.c_kind(frame),kind)
   for pos in range(len(frame)):
    bad=bytearray(frame);bad[pos]^=1
    self.assertEqual(self.c_kind(bytes(bad)),0)
 def test_profile_defaults_no_motion(self):
  rows=nh22.load_profile(ROOT/"config/channels.json")
  self.assertEqual(len(rows),22)
  self.assertFalse(any(r["enabled"] for r in rows))
  with self.assertRaises(ValueError):nh22.prepare_pose(rows,["F01=1500"])
 def test_unverified_profile_rejected(self):
  with tempfile.NamedTemporaryFile(mode="w",suffix=".json",dir=ROOT/"build/verification",delete=False) as f:
   value=json.loads((ROOT/"config/channels.json").read_text(encoding="utf-8-sig"));value["channels"][0]["enabled"]=True
   json.dump(value,f);path=Path(f.name)
  try:
   with self.assertRaises(ValueError):nh22.load_profile(path)
  finally:path.unlink()
 def test_telemetry_crc(self):
  out=b"NT\x03\x06"+struct.pack("<9I",12,0,0,0,1,2,3,4,5)+struct.pack("<44H",*([1500]*44))
  data=nh22.seal(out)
  self.assertEqual(len(data),130)
  self.assertEqual(nh22.decode_telemetry(data)["sequence"],12)
  with self.assertRaises(ValueError):nh22.decode_telemetry(data[:-1]+bytes((data[-1]^1,)))
 def test_dry_run_and_query_loopback(self):
  result=subprocess.check_output([sys.executable,str(ROOT/"src/pc/nh22.py"),"configure"])
  self.assertTrue(json.loads(result)["dry_run"])
  server=socket.socket(socket.AF_INET,socket.SOCK_DGRAM);server.bind(("127.0.0.1",0));server.settimeout(2)
  errors=[]
  def serve():
   try:
    data,peer=server.recvfrom(2048)
    assert self.c_kind(data)==1
    timestamp=struct.unpack_from("<I",data,6)[0]
    reply=b"NT\x03\x02"+struct.pack("<9I",0,0,0,0,0,0,0,0,timestamp)+bytes(88)
    server.sendto(nh22.seal(reply),peer)
   except Exception as e:errors.append(e)
  thread=threading.Thread(target=serve);thread.start()
  client=nh22.Client("127.0.0.1",server.getsockname()[1]);client.close()
  thread.join();server.close()
  self.assertFalse(errors)
if __name__=="__main__":unittest.main(verbosity=2)
