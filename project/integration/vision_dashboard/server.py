"""Loopback-only read-only dashboard. No camera, controller, or board imports."""
import argparse,json,math,threading,time
from pathlib import Path
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
ROOT=Path(__file__).resolve().parents[2]
MAX_BYTES=2_000_000

def read_json(path):
    if path.stat().st_size>MAX_BYTES:raise ValueError('文件超过只读面板大小限制')
    return json.loads(path.read_text(encoding='utf-8-sig'))

def finite(v):return type(v) in (int,float) and math.isfinite(v)
def age(stamp,now):return now-stamp if finite(stamp) else None

def vision_state(row,now):
    v=row.get('vision',{});a=age(row.get('captured_monotonic'),now)
    fresh=(row.get('device')=='USB Cam' and a is not None and 0<=a<=.75 and
        v.get('running') is True and not v.get('error'))
    result=dict(fresh=fresh,age_ms=round(a*1000,1) if a is not None else None,
        source='USB Cam',frame_id=v.get('frame_id'),session=v.get('source_session_id'),
        width=v.get('width'),height=v.get('height'),detector=v.get('detector'),
        detection_ms=v.get('detection_ms') if finite(v.get('detection_ms')) else None,
        capture_ms=None,preprocess_ms=None,selection_ms=None,
        target=None,box=None,face_count=0,jpeg=None)
    if not fresh:return result
    target=v.get('target');box=v.get('box')
    if target is not None and (not isinstance(target,list) or len(target)!=2 or
        not all(finite(x) and -1<=x<=1 for x in target)):
        raise ValueError('人脸中心坐标格式无效')
    if box is not None and (not isinstance(box,list) or len(box)!=4 or
        not all(finite(x) for x in box) or box[2]<=0 or box[3]<=0):raise ValueError('目标框无效')
    jpeg=row.get('jpeg')
    if not isinstance(jpeg,str) or len(jpeg)>1_800_000:raise ValueError('共享JPEG无效')
    result.update(jpeg=jpeg,target=target,box=box,face_count=v.get('face_count',0))
    return result

def controller_state(folder,now):
    candidates=[]
    for p in folder.glob('head_runtime_*.json'):
        try:
            d=read_json(p);a=age(d.get('updated_epoch'),now)
            if a is not None and 0<=a<3:candidates.append(d)
        except (OSError,ValueError,TypeError):continue
    if not candidates:return dict(fresh=False,mode='offline',desired_us=None,output_us=None)
    # Prefer the active owner; an idle UI must not eclipse the actual sender.
    d=max(candidates,key=lambda d:(d.get('mode') in ('running','paused','fault'),d['updated_epoch']))
    def five(key):
        v=d.get(key)
        return v if isinstance(v,list) and len(v)==5 and all(finite(x) for x in v) else None
    return dict(fresh=True,mode=d.get('mode'),tracking=d.get('tracking'),
        desired_us=five('desired_us'),output_us=five('output_pwm_us'),
        frontal_preferred=d.get('frontal_preferred') is True,
        frontal_active=(d.get('mode')=='running' and d.get('tracking')=='coordinated' and
                        d.get('motion_style')=='natural' and d.get('frontal_preferred') is True),
        motion_style=d.get('motion_style'),reference_us=five('reference_us'),
        active_mask=d.get('active_mask'),age_ms=round((now-d['updated_epoch'])*1000,1),
        worker_max_gap_s=d.get('worker_max_gap_s'),life_state=d.get('life_state'),
        error=d.get('error'),source='异步主控快照；非关节角反馈')

class Monitor:
    def __init__(self,root=ROOT):
        self.root=Path(root);self.lock=threading.Lock();self.last=None;self.fps=None
    def snapshot(self):
        result=dict(read_only=True,vision=dict(fresh=False,jpeg=None,target=None,box=None),
                    controller=controller_state(self.root/'build',time.time()),message='等待共享 USB Cam')
        try:
            v=vision_state(read_json(self.root/'build/usb_cam_shared.json'),time.monotonic())
            result['vision']=v
            if v['fresh']:
                key=(v['session'],v['frame_id']);stamp=time.monotonic()-v['age_ms']/1000
                with self.lock:
                    if self.last and key[0]==self.last[0][0] and key[1]>self.last[0][1] and stamp>self.last[1]:
                        f=(key[1]-self.last[0][1])/(stamp-self.last[1])
                        self.fps=f if self.fps is None else .8*self.fps+.2*f
                    elif not self.last or key[0]!=self.last[0][0]:self.fps=None
                    if not self.last or key!=self.last[0]:self.last=(key,stamp)
                    v['fps']=round(self.fps,1) if self.fps is not None else None
                result['message']='正在处理 / 已选择最大面积人脸' if v['target'] is not None else '画面实时 / 当前无人脸'
            else:result['message']='画面已过期或采集中断；不显示旧画面为实时结果'
        except (OSError,ValueError,TypeError,KeyError) as exc:
            result['message']='等待共享 USB Cam：'+str(exc)
        return result

def make_handler(monitor):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self,*args):pass
        def do_GET(self):
            route=self.path.split('?',1)[0]
            if route=='/':body=(Path(__file__).parent/'index.html').read_bytes();kind='text/html; charset=utf-8'
            elif route=='/api/state':body=json.dumps(monitor.snapshot(),ensure_ascii=False,allow_nan=False).encode('utf-8');kind='application/json; charset=utf-8'
            elif route=='/health':body=b'{"read_only":true,"service":"nh_vision_dashboard"}';kind='application/json'
            else:self.send_error(404);return
            self.send_response(200);self.send_header('Content-Type',kind)
            self.send_header('Cache-Control','no-store');self.send_header('X-Content-Type-Options','nosniff')
            self.send_header('Content-Length',str(len(body)));self.end_headers();self.wfile.write(body)
    return Handler

def main():
    p=argparse.ArgumentParser();p.add_argument('--port',type=int,default=8766);a=p.parse_args()
    server=ThreadingHTTPServer(('127.0.0.1',a.port),make_handler(Monitor()))
    print('READ_ONLY_VISION_DASHBOARD http://127.0.0.1:%d'%a.port,flush=True)
    try:server.serve_forever()
    except KeyboardInterrupt:pass
    finally:server.server_close()
if __name__=='__main__':main()
