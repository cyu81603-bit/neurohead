import sys,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src/pc'))
from external_vision_source import PreviewFeed
class Source:
    def __init__(self):self.packet=dict(frame_id=0,error=None);self.closed=False
    def start(self):return self
    def snapshot(self):return self.packet,'frame'
    def close(self):self.closed=True
class CameraRecovery(unittest.TestCase):
    def setUp(self):
        self.now=0.;self.sources=[]
        def factory():
            s=Source();self.sources.append(s);return s
        self.feed=PreviewFeed(factory,lambda:self.now)
    def test_new_frames_only(self):
        self.feed.step();self.sources[0].packet=dict(frame_id=1,error=None,target=[0,0])
        self.assertTrue(self.feed.step()[2]);self.assertFalse(self.feed.step()[2])
    def test_error_clears_old_detection(self):
        self.feed.step();self.sources[0].packet=dict(frame_id=1,error='I/O',target=[.5,.5])
        self.assertEqual(self.feed.step(),(None,None,False));self.assertTrue(self.sources[0].closed)
        self.assertEqual(self.feed.error,'I/O')
    def test_bounded_backoff_and_manual_retry(self):
        for i in range(3):
            self.feed.step();self.sources[-1].packet['error']='I/O';self.feed.step()
            count=len(self.sources);self.now+=.1;self.feed.step();self.assertEqual(len(self.sources),count)
            self.now+=10
        self.feed.step();self.assertEqual(len(self.sources),3)
        self.feed.retry();self.feed.step();self.assertEqual(len(self.sources),4)
    def test_stalled_stream_and_close(self):
        self.feed.step();self.sources[0].packet=dict(frame_id=1,error=None);self.feed.step()
        self.now=4;self.feed.step();self.assertIsNone(self.feed.source);self.assertTrue(self.feed.error)
        self.feed.close();self.now=30;self.feed.step();self.assertEqual(len(self.sources),1)
    def test_startup_timeout(self):
        self.feed.step();self.now=16;self.feed.step();self.assertIsNone(self.feed.source)
        self.assertIn('USB Cam',self.feed.error)
if __name__=='__main__':unittest.main()
