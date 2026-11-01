import copy,json,math,sys,tempfile,time,unittest,wave,threading,urllib.request,urllib.error,types
from pathlib import Path
from unittest.mock import patch
import numpy as np
ROOT=Path(__file__).resolve().parents[1];sys.path[:0]=[str(ROOT/'src/pc'),str(ROOT/'sim')]
from lifelike_behavior import ExpressionEngine,SpeechState,approved_poses
from lifelike_control import LifelikeControl
from frontal_gaze import FrontalCoordinator
from head_motion import NaturalCoordinator
from head_control import MASK
from test_head_control import profile,Lock
from test_face_commission import Board
from speech_audio import envelope,AudioPlayer
from lifelike_api import IntentServer

def config(ready=()):
    c=json.loads((ROOT/'config/lifelike.json').read_text(encoding='utf-8'))
    for p in c['poses']:
        p['max_rate_us_per_s']=4000 if p['channel'] in range(6,10) else 1500 if p['channel']==21 else 600 if p['channel'] in range(10,14) else 150
        for key in ('probe_only','neutral_verified','forbidden_pulses_us'):p.pop(key,None)
        p.update(neutral_us=1500,min_us=1100,max_us=1900,action_us=1600 if p['channel']%2==0 else 1400,range_confirmed=True,action_verified=p['channel'] in ready,enabled=p['channel'] in ready)
    return c
class BehaviorTests(unittest.TestCase):
    def test_unverified_direction_outputs_no_faces(self):
        e=ExpressionEngine(config(),0,1);e.enable(0)
        for i in range(100):self.assertEqual(e.step(i*.05),{})
        self.assertEqual(len(e.blocked),17)
    def test_blink_bilateral_bounds_and_camera_hold(self):
        e=ExpressionEngine(config((6,8)),0,1);e.enable(0);e.step(.6);self.assertTrue(e.blink_once(.6));self.assertTrue(e.vision_hold(.7))
        values=[]
        for i in range(100):
            out=e.step(.6+i*.02);values.append(out)
            self.assertTrue(all(1100<=x<=1900 for x in out.values()))
            self.assertAlmostEqual((out[6]-1500)/100,(out[8]-1500)/100,delta=.02)
        self.assertGreater(max(x[6] for x in values),1590);self.assertFalse(e.vision_hold(3))
    def test_default_full_range_blink_has_bounded_subsecond_timing(self):
        cfg=config((6,8))
        for p in cfg['poses']:
            if p['channel'] in (6,8):p['action_us']=1900
        e=ExpressionEngine(cfg,0,1);e.enable(0);e.step(.6);e.blink_once(.6)
        self.assertLess(e.vision_until-.6,1.)
        self.assertTrue(all(p['max_rate_us_per_s']<=5000 for p in e.poses.values()))
    def test_one_unverified_eye_prevents_automatic_blink(self):
        e=ExpressionEngine(config((6,)),0,1);e.enable(0);self.assertFalse(e.blink_once(1));self.assertFalse(e.vision_hold(1))
    def test_speech_silence_closes_mouth_and_voice_animates_brows(self):
        e=ExpressionEngine(config((2,4,21)),0,1);e.enable(0);e.step(.6);e.speech.timeline([1.]*50+[0.]*100,.02,.6)
        loud=[]
        for i in range(100):loud.append(e.step(.6+i*.02))
        self.assertLess(min(x[21] for x in loud[:45]),1480)
        self.assertGreater(max(x[2] for x in loud),1501)
        for i in range(200):last=e.step(2.6+i*.02)
        self.assertAlmostEqual(last[21],1500,delta=1)
    def test_stale_tts_energy_and_bad_values(self):
        s=SpeechState();s.external(.8,1,'tts');self.assertTrue(s.sample(1.2)[1]);self.assertEqual(s.sample(1.4),(0.,False))
        for x in (float('nan'),-1,2):
            with self.assertRaises(ValueError):s.external(x,2)
    def test_old_file_end_cannot_stop_new_tts(self):
        s=SpeechState();token=s.timeline([1],.02,0);s.sample(.1);s.external(.7,.2,'new');s.stop(token);self.assertEqual(s.sample(.21),(.7,True))
    def test_motion_stays_bounded_and_stop_returns_neutral(self):
        e=ExpressionEngine(config(range(2,18)),0,1);e.enable(0);e.speech.external(1,.6)
        for i in range(200):
            out=e.step(i*.05,1)
            self.assertTrue(all(1100<=x<=1900 for x in out.values()))
        e.stop(10)
        for i in range(300):out=e.step(10+i*.05)
        self.assertEqual(e.state,'off');self.assertEqual(out,{})
    def test_head_prefers_frontal_without_expanding_neck(self):
        def simulate(cls):
            p=profile();v=[1500,1500,1500,1270,1500];c=cls(p,v);cal=dict(valid=True,reference_us=[1500,1270,1500],inverse=[[500,0],[0,200]],automatic_yaw_limit_us=100,automatic_pitch_limit_us=100,automatic_yaw_rate_us_per_s=20,automatic_pitch_rate_us_per_s=15)
            for i in range(400):
                x=.12+.002*(v[0]-1500)+.002*(v[2]-1500);v=c.update(dict(frame_id=i,frame_time=i*.05,target=[x,0]),v,cal)
                self.assertTrue(1400<=v[2]<=1600 and 1170<=v[3]<=1370 and 1400<=v[4]<=1600)
            return abs(v[0]-1500)
        self.assertLess(simulate(FrontalCoordinator),simulate(NaturalCoordinator))
class ControlTests(unittest.TestCase):
    def make(self,ready=()):
        Board.instances=[];Board.fail=False;self.clock=[0.]
        c=LifelikeControl(dict(profile(),lifelike=config(ready)),clock=lambda:self.clock[0],client_factory=Board,lock_factory=lambda _:Lock());c._guard=lambda:None
        with patch('eye_follow_panel.verified_command',return_value=[]):c.start()
        return c
    def test_start_only_head_and_unapproved_stays_off(self):
        c=self.make();c.tick(.05);self.assertEqual(c.last_state['active_mask'],MASK);c.enable_life(False)
        for i in range(20):self.clock[0]=i*.05;c.tick(.05);self.assertEqual(c.last_state['active_mask'],MASK)
        c.end(True)
    def test_only_approved_channels_mix_and_pause_removes_faces(self):
        c=self.make((2,21))
        with self.assertRaises(ValueError):c.enable_life(False)
        c.enable_life(True);c.tick(.05);self.assertEqual(c.last_state['active_mask'],MASK|4|(1<<21));c.pause();c.tick(.05);self.assertEqual(c.last_state['active_mask'],MASK);c.end(True)
    def test_preview_only_selected_returns_and_requires_observation(self):
        c=self.make()
        with self.assertRaises(ValueError):c.approve_pose(2)
        c.preview_joint(2,True)
        for i in range(220):self.clock[0]=i*.05;c.tick(.05)
        self.assertIsNone(c.preview);self.assertEqual(c.last_state['active_mask'],MASK);self.assertNotIn(2,c.engine.poses)
        cfg=c.approve_pose(2);self.assertTrue(cfg['poses'][0]['enabled']);self.assertIn(2,c.engine.poses)
        c.end(True)
    def test_blink_does_not_skip_visual_tracking(self):
        c=self.make((6,8));c.enable_life(True);c.engine.blink_once(0);c.tracking='eyes'
        with patch('head_control.HeadControl._visual_tick') as read:
            self.clock[0]=.1;c._visual_tick();read.assert_called_once();self.clock[0]=4;c._visual_tick();self.assertEqual(read.call_count,2)
        c.end(True)
    def test_audio_ownership_and_raw_pwm_rejected(self):
        c=self.make((21,));c.enable_life(True);token=c.speech_timeline([.8]*50,.02,'file')
        with self.assertRaises(ValueError):c.life_event({'type':'speech.energy','energy':.7})
        with self.assertRaises(ValueError):c.life_event({'type':'set_pwm','channel':21,'us':2400})
        c.life_event({'type':'speech.end','token':token});self.assertIsNone(c.engine.speech.kind);c.end(True)
    def test_reverse_point_invalidates_automatic_approval(self):
        c=self.make((2,));p=copy.deepcopy(c.pose_map[2]);p['action_us']=1400;cfg=c.update_pose(p);self.assertFalse(cfg['poses'][0]['enabled']);c.end(True)
class AudioTests(unittest.TestCase):
    def test_pcm_energy_distinguishes_silence_without_playback(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'speech.wav';rate=16000;t=np.arange(3200)/rate;tone=(np.sin(2*np.pi*240*t)*12000).astype('<i2');data=np.concatenate([np.zeros(3200,dtype='<i2'),tone,np.zeros(3200,dtype='<i2')])
            with wave.open(str(p),'wb') as w:w.setnchannels(1);w.setsampwidth(2);w.setframerate(rate);w.writeframes(data.tobytes())
            values,step=envelope(p);self.assertEqual(step,.02);self.assertTrue(all(x==0 for x in values[:10]+values[-10:]));self.assertGreater(min(values[10:20]),.8)
    def test_stop_during_decode_never_starts_late_playback(self):
        import speech_audio as module
        entered=threading.Event();release=threading.Event();session=types.SimpleNamespace(speech_timeline=lambda *a:1,life_event=lambda *a:None)
        def decode(_):entered.set();release.wait(1);return Path('fake.wav'),[1.],.02
        sound=types.SimpleNamespace(PlaySound=lambda *a:None,SND_FILENAME=1,SND_NODEFAULT=2,SND_ASYNC=4)
        with patch.object(module,'prepare_audio',side_effect=decode),patch.dict(sys.modules,{'winsound':sound}),patch.object(sound,'PlaySound') as play:
            player=AudioPlayer(session);player.play('fake');self.assertTrue(entered.wait(1));player.stop();release.set();player.worker.join(1)
            self.assertFalse(any(call.args[0]=='fake.wav' for call in play.call_args_list))
class ApiTests(unittest.TestCase):
    def test_loopback_requires_key_and_rejects_raw_pwm(self):
        events=[];session=types.SimpleNamespace(extra={},life_event=lambda e:events.append(e));server=IntentServer(session,0).start();url='http://127.0.0.1:'+str(server.port)+'/events'
        try:
            def post(payload,key=None):
                req=urllib.request.Request(url,json.dumps(payload).encode(),headers={'X-NeuroHead-Key':key or ''})
                return urllib.request.urlopen(req,timeout=2).status
            with self.assertRaises(urllib.error.HTTPError):post({'type':'blink'})
            self.assertEqual(post({'type':'speech.energy','energy':.5},server.token),200);self.assertEqual(len(events),1)
            with self.assertRaises(urllib.error.HTTPError):post({'type':'set_pwm','channel':21,'us':2400},server.token)
            self.assertEqual(len(events),1)
        finally:server.stop()
if __name__=='__main__':unittest.main(verbosity=2)
