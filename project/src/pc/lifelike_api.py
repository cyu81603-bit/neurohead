"""Loopback intent API for a later LLM/TTS integration; no raw servo commands."""
import json,secrets,threading
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
class IntentServer:
    def __init__(self,session,port=8765):
        self.session=session;self.token=secrets.token_urlsafe(24);owner=self
        class Handler(BaseHTTPRequestHandler):
            def log_message(self,*_):pass
            def reply(self,status,value):
                data=json.dumps(value,ensure_ascii=False).encode('utf-8');self.send_response(status);self.send_header('Content-Type','application/json; charset=utf-8');self.send_header('Content-Length',str(len(data)));self.end_headers();self.wfile.write(data)
            def do_GET(self):
                if self.path!='/status':self.reply(404,{'error':'not found'});return
                extra=owner.session.extra;self.reply(200,{k:extra.get(k) for k in ('life_state','life_ready_channels','life_blocked','speech','blink_ratio','action_library_enabled','action_active','action_pending','action_last')})
            def do_POST(self):
                if self.path!='/events':self.reply(404,{'error':'not found'});return
                if self.headers.get('X-NeuroHead-Key')!=owner.token:self.reply(403,{'error':'key required'});return
                try:
                    size=int(self.headers.get('Content-Length','0'))
                    if not 0<size<=262144:raise ValueError('invalid body size')
                    value=json.loads(self.rfile.read(size))
                    if not isinstance(value,dict):raise ValueError('object required')
                    if value.get('type') not in ('stop','speech.end','speech.energy','blink','expression','action','action.cancel'):raise ValueError('Only registered action/expression/speech intents allowed; raw PWM rejected')
                    result=owner.session.life_event(value);self.reply(200,{'ok':True,'result':result})
                except Exception as exc:self.reply(400,{'error':str(exc)})
        self.server=ThreadingHTTPServer(('127.0.0.1',port),Handler);self.port=self.server.server_address[1];self.thread=threading.Thread(target=self.server.serve_forever,name='local-expression-api',daemon=True)
    def start(self):self.thread.start();return self
    def stop(self):self.server.shutdown();self.server.server_close();self.thread.join(.5)
