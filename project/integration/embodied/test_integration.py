"""Cross-component contracts with fake audio/session, never hardware IO."""
import json
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

HERE=Path(__file__).resolve().parent
PROJECT=HERE.parents[1]
sys.path.insert(0,str(PROJECT/'src/pc'))
sys.path.insert(0,str(HERE))
import numpy as np
import intent_link
import vision_share
from lifelike_behavior import ExpressionEngine


class FakeSession:
    def __init__(self):
        self.mode='running';self.extra={'life_state':'active'};self.events=[]
    def life_event(self,event):self.events.append(event)


class LinkTests(unittest.TestCase):
    def setUp(self):self.session=FakeSession();self.link=intent_link.IntentLink(self.session)
    def test_default_does_not_send_intents(self):
        self.link.begin('a','笑',2);self.link.energy('a',.8);self.link.end('a')
        self.assertEqual(self.session.events,[])
    def test_idle_controller_cannot_be_started_by_llm(self):
        self.session.mode='idle'
        with self.assertRaises(ValueError):self.link.enable()
        self.assertFalse(self.link.enabled)
    def test_running_without_expression_approval_rejected(self):
        self.session.extra['life_state']='off'
        with self.assertRaises(ValueError):self.link.enable()
    def test_actual_contract_and_emotions(self):
        self.link.enable();self.link.begin('a','难过',40);self.link.energy('a',.8);self.link.end('a')
        self.assertEqual(self.session.events,[dict(type='expression',name='sad',duration_s=20.),
                                             dict(type='speech.energy',id='a',energy=.8),dict(type='speech.end')])
        self.assertEqual(intent_link.expression_name('任意PWM命令'),'neutral')
    def test_named_presets_and_wink_use_intent_whitelist(self):
        self.link.enable();self.link.begin('wink','wink',1)
        self.assertEqual(self.session.events[0],dict(type='expression',name='wink',duration_s=1.))
        self.assertEqual(intent_link.expression_name('微笑'),'smile')
        self.assertEqual(intent_link.expression_name('笑'),'happy')
    def test_late_old_audio_cannot_cancel_new_audio(self):
        self.link.enable();self.link.begin('a','笑',1);self.link.begin('b',None,1)
        self.link.energy('a',1);self.link.end('a')
        self.assertEqual(self.link.speaking_id,'b')
        self.assertEqual(len(self.session.events),2)
    def test_energy_rejects_nan_inf_and_unbounded(self):
        for value in (float('nan'),float('inf'),-.1,1.1,'0.5'):
            with self.assertRaises(ValueError):self.link.energy('a',value)
    def test_disconnect_only_ends_speech_never_neck_stop(self):
        self.link.enable();self.link.begin('a','笑',1);self.link.disable()
        self.assertEqual(self.session.events[-1],{'type':'speech.end'})
        self.assertFalse(self.link.enabled)
        self.assertFalse(any(x['type']=='stop' for x in self.session.events))


class FrameTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.path=Path(self.temp.name)/'frame.json'
        self.packet=dict(frame_id=1,source_session_id='session',frame_time=10.,running=True,error=None,target=[.2,.1])
    def tearDown(self):self.temp.cleanup()
    def test_single_shared_usb_frame(self):
        vision_share.publish(self.packet,np.zeros((20,20,3),np.uint8),self.path)
        row=vision_share.read(self.path,now=10.2)
        self.assertEqual(row['device'],'USB Cam');self.assertEqual(row['vision']['target'],[.2,.1])
        self.assertTrue(row['jpeg'])
    def test_stale_future_and_wrong_camera_rejected(self):
        vision_share.publish(self.packet,np.zeros((20,20,3),np.uint8),self.path)
        for now in (9.,11.):
            with self.assertRaises(ValueError):vision_share.read(self.path,now=now)
        row=json.loads(self.path.read_text(encoding='utf-8'));row['device']='Builtin Camera'
        self.path.write_text(json.dumps(row),encoding='utf-8')
        with self.assertRaises(ValueError):vision_share.read(self.path,now=10.1)
    def test_capture_error_not_republished_as_fresh(self):
        vision_share.publish(dict(self.packet,error='USB unplugged'),np.zeros((20,20,3),np.uint8),self.path)
        self.assertFalse(self.path.exists())
    def test_shared_frame_io_failure_never_breaks_tracking_capture(self):
        with patch('vision_share.os.replace',side_effect=PermissionError('reader busy')):
            self.assertFalse(vision_share.publish(self.packet,np.zeros((20,20,3),np.uint8),self.path))


class CalibrationTests(unittest.TestCase):
    def test_current_lids_neck_and_jaw_are_authoritative(self):
        cfg=json.loads((PROJECT/'config/lifelike_v4.json').read_text(encoding='utf-8'))
        engine=ExpressionEngine(cfg)
        self.assertIn(6,engine.poses);self.assertIn(8,engine.poses)
        self.assertEqual(engine.poses[6]['action_us'],1900)
        self.assertNotIn(21,engine.poses)
        # Operator approvals/speed can legitimately change in the live panel.
        for ch in range(14,18):
            p=next(p for p in cfg['poses'] if p['channel']==ch)
            if not p.get('enabled') or not p.get('action_verified'):self.assertNotIn(ch,engine.poses)
        rates=cfg['neck_tracking_rate_us_per_s']
        self.assertTrue(0<rates[0]<=50 and 0<rates[1]<=35)
    def test_sad_stays_inside_approved_pose_directions(self):
        cfg=json.loads((PROJECT/'config/lifelike_v4.json').read_text(encoding='utf-8'))
        engine=ExpressionEngine(cfg,seed=1);engine.enable(0);engine.mood='sad';engine.mood_end=5
        for i in range(1,150):
            output=engine.step(i*.02)
            for ch,u in output.items():
                p=engine.poses[ch];lo,hi=sorted((p['neutral_us'],p['action_us']))
                self.assertLessEqual(lo,u);self.assertLessEqual(u,hi)
        self.assertNotIn(21,output)
    def test_legacy_jaw_metadata_has_zero_travel(self):
        import config
        self.assertEqual(config.FACE_CHANNEL_CONFIG['jaw_mouth']['max_open_delta_us'],0)


class BrainContractTests(unittest.TestCase):
    def test_wink_response_keeps_tracking_and_only_emits_named_intent(self):
        from qwen_brain import QwenEmbodiedBrain
        result=QwenEmbodiedBrain._parse_llm_response(json.dumps(dict(reply_text='给你一个wink。',expression='wink',gaze_mode='tilt_left')),'眨一下右眼')
        self.assertEqual(result,('眨一下右眼','wink','track_face','给你一个wink。'))
    def test_structured_reply_has_required_answer_and_bounded_intent(self):
        from qwen_brain import QwenEmbodiedBrain
        packet=json.dumps(dict(reply_text='画面主要是红色。',expression='任意舵机动作',gaze_mode='danger',corrected_user_text='看颜色'))
        result=QwenEmbodiedBrain._parse_llm_response(packet,'原话')
        self.assertEqual(result,('看颜色',None,'track_face','画面主要是红色。'))
    def test_empty_structured_reply_is_not_a_valid_answer(self):
        from qwen_brain import QwenEmbodiedBrain
        result=QwenEmbodiedBrain._parse_llm_response('{"expression":"笑"}','原话')
        self.assertEqual(result[-1],'')


class AudioTests(unittest.TestCase):
    def test_audio_cursor_drives_intents_without_jaw_commands(self):
        import speech_output,sounddevice
        class Stream:
            def __init__(self,**kwargs):pass
            def __enter__(self):return self
            def __exit__(self,*_):pass
            def write(self,chunk):time.sleep(.02)
            def abort(self):pass
        session=FakeSession();link=intent_link.IntentLink(session);link.enable()
        player=speech_output.SpeechOutput(link)
        pcm=np.full(6400,2000,dtype=np.int16)
        records=[dict(start_ms=0,end_ms=400,norm_amplitude=.8)]
        with patch.object(speech_output,'synthesize_tts_pcm',return_value=pcm),patch.object(speech_output,'compute_per_character_amplitudes',return_value=records),patch.object(sounddevice,'OutputStream',Stream):
            player.speak('测试','笑');player.worker.join(3)
        self.assertFalse(player.worker.is_alive())
        self.assertEqual(session.events[0]['name'],'happy')
        self.assertGreater(len([e for e in session.events if e['type']=='speech.energy']),2)
        self.assertEqual(session.events[-1],{'type':'speech.end'})
        self.assertTrue(all(set(e).issubset({'type','id','energy','name','duration_s'}) for e in session.events))
    def test_no_pcm_never_sends_mouth_motion(self):
        import speech_output
        session=FakeSession();link=intent_link.IntentLink(session);link.enable();events=[]
        player=speech_output.SpeechOutput(link,lambda k,v:events.append((k,v)))
        with patch.object(speech_output,'synthesize_tts_pcm',return_value=np.zeros(0,dtype=np.int16)):
            player.speak('测试','笑');player.worker.join(2)
        self.assertEqual(session.events,[])
        self.assertTrue(any(k=='error' for k,v in events))
    def test_cancel_during_synthesis_never_starts_audio_or_intents(self):
        import speech_output,threading
        entered=threading.Event();release=threading.Event()
        def synth(*_):entered.set();release.wait(2);return np.ones(320,dtype=np.int16)
        session=FakeSession();link=intent_link.IntentLink(session);link.enable()
        player=speech_output.SpeechOutput(link)
        with patch.object(speech_output,'synthesize_tts_pcm',side_effect=synth):
            player.speak('测试','笑');self.assertTrue(entered.wait(2));player.stop();release.set();player.worker.join(2)
        self.assertEqual(session.events,[]);self.assertFalse(player.playing)


if __name__=='__main__':unittest.main(verbosity=2)
