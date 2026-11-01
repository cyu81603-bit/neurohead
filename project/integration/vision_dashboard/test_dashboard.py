import json, tempfile, unittest, threading, urllib.request, urllib.error
from pathlib import Path
from http.server import ThreadingHTTPServer
from server import vision_state, controller_state, Monitor, make_handler

class DashboardTests(unittest.TestCase):
    def sample(self):
        return dict(device='USB Cam', captured_monotonic=100, vision=dict(running=True, error=None, target=[.25,-.5], box=[1,2,30,40], frame_id=4, source_session_id='a', face_count=1, width=640, height=480, detection_ms=12), jpeg='ZmFrZQ==')

    def test_live_values_are_source_values(self):
        v=vision_state(self.sample(),100.1)
        self.assertTrue(v['fresh']);self.assertEqual(v['detection_ms'],12)
        self.assertEqual(v['target'],[.25,-.5]);self.assertIsNone(v['preprocess_ms'])

    def test_stale_image_and_target_are_removed(self):
        v=vision_state(self.sample(),101)
        self.assertFalse(v['fresh']);self.assertIsNone(v['jpeg']);self.assertIsNone(v['target'])

    def test_no_face_is_a_live_frame(self):
        r=self.sample();r['vision'].update(target=None,box=None,face_count=0)
        v=vision_state(r,100);self.assertTrue(v['fresh']);self.assertIsNone(v['target'])

    def test_invalid_target_is_rejected(self):
        for value in (float('nan'),3):
            r=self.sample();r['vision']['target']=[value,0]
            with self.assertRaises(ValueError):vision_state(r,100)

    def test_active_owner_wins_without_extra_fields(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)
            (p/'head_runtime_1.json').write_text(json.dumps(dict(updated_epoch=99,mode='running',output_pwm_us=[1500]*5,private='hidden')))
            (p/'head_runtime_2.json').write_text(json.dumps(dict(updated_epoch=100,mode='idle')))
            c=controller_state(p,100)
            self.assertEqual(c['mode'],'running');self.assertNotIn('private',c)
            self.assertFalse(controller_state(p,105)['fresh'])

    def test_frontal_requires_actual_coordinated_natural_running_mode(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'head_runtime_1.json'
            row=dict(updated_epoch=100,mode='running',tracking='eyes',motion_style='natural',frontal_preferred=True)
            p.write_text(json.dumps(row))
            self.assertFalse(controller_state(Path(d),100)['frontal_active'])
            row['tracking']='coordinated';p.write_text(json.dumps(row))
            self.assertTrue(controller_state(Path(d),100)['frontal_active'])
            for key,value in [('mode','paused'),('motion_style','legacy'),('frontal_preferred',False)]:
                changed=dict(row);changed[key]=value;p.write_text(json.dumps(changed))
                self.assertFalse(controller_state(Path(d),100)['frontal_active'])

    def test_read_only_http(self):
        with tempfile.TemporaryDirectory() as d:
            Path(d,'build').mkdir()
            s=ThreadingHTTPServer(('127.0.0.1',0),make_handler(Monitor(d)))
            t=threading.Thread(target=s.serve_forever,daemon=True);t.start()
            base='http://127.0.0.1:'+str(s.server_port)
            try:
                data=json.load(urllib.request.urlopen(base+'/api/state'))
                self.assertTrue(data['read_only']);self.assertFalse(data['vision']['fresh'])
                for request,status in ((urllib.request.Request(base+'/api/state',data=b'{}',method='POST'),501),(base+'/not-a-route',404)):
                    with self.assertRaises(urllib.error.HTTPError) as e:urllib.request.urlopen(request)
                    self.assertEqual(e.exception.code,status)
            finally:s.shutdown();s.server_close();t.join()

if __name__=='__main__':unittest.main()
