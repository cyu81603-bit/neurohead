"""LLM/TTS intent client. CLI is dry-run unless --send is explicitly supplied."""
import argparse,json,math
from pathlib import Path
from urllib.request import Request,urlopen
class NeuroHeadClient:
    def __init__(self,url,key):
        if url.rstrip('/') not in ('http://127.0.0.1:8765','http://localhost:8765'):raise ValueError('Use local robot intent endpoint on port8765')
        self.url=url.rstrip('/');self.key=key
    @classmethod
    def from_file(cls,path):
        cfg=json.loads(Path(path).read_text(encoding='utf-8'));return cls(cfg['url'],cfg['key'])
    def event(self,value):
        req=Request(self.url+'/events',data=json.dumps(value).encode('utf-8'),headers={'Content-Type':'application/json','X-NeuroHead-Key':self.key},method='POST')
        with urlopen(req,timeout=2) as response:return json.load(response)
    def energy(self,value,utterance_id='tts'):
        if type(value) not in (int,float) or not math.isfinite(value) or not 0<=value<=1:raise ValueError('Energy must be finite0..1')
        return self.event(dict(type='speech.energy',energy=value,id=utterance_id))
    def end_speech(self):return self.event({'type':'speech.end'})
    def expression(self,name,duration=2):
        if name not in ('neutral','engaged','happy','curious'):raise ValueError('Unknown expression')
        return self.event(dict(type='expression',name=name,duration_s=duration))
    def blink(self):return self.event({'type':'blink'})

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--send',action='store_true');p.add_argument('--api-file',type=Path)
    p.add_argument('--event',choices=['expression','blink','speech.end','speech.energy'],default='expression');p.add_argument('--name',default='engaged');p.add_argument('--energy',type=float,default=.5);p.add_argument('--duration',type=float,default=2);a=p.parse_args()
    value={'type':a.event}
    if a.event=='expression':value.update(name=a.name,duration_s=a.duration)
    if a.event=='speech.energy':value.update(energy=a.energy,id='tts-example')
    if not a.send:print(json.dumps(dict(dry_run=True,event=value),ensure_ascii=False));return
    if a.api_file is None:p.error('--send requires the current locally generated --api-file; no key is bundled')
    print(json.dumps(NeuroHeadClient.from_file(a.api_file).event(value)))
if __name__=='__main__':main()
