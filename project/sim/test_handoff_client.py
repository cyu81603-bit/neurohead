import sys,unittest,json,io
from pathlib import Path
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'examples'))
from tts_client import NeuroHeadClient
class ClientTests(unittest.TestCase):
 def test_serializes_intent_and_key_without_robot_backend(self):
  client=NeuroHeadClient('http://127.0.0.1:8765','test-key')
  with patch('tts_client.urlopen') as send:
   send.return_value.__enter__.return_value=io.BytesIO(b'{"ok":true}')
   self.assertEqual(client.energy(.6,'one'),{'ok':True});req=send.call_args.args[0]
   self.assertEqual(req.full_url,'http://127.0.0.1:8765/events');self.assertEqual(json.loads(req.data),{'type':'speech.energy','energy':.6,'id':'one'})
 def test_bad_energy_never_sends(self):
  client=NeuroHeadClient('http://127.0.0.1:8765','test-key')
  with patch('tts_client.urlopen') as send:
   for value in [float('nan'),-1,2]:
    with self.assertRaises(ValueError):client.energy(value)
   send.assert_not_called()
if __name__=='__main__':unittest.main()
