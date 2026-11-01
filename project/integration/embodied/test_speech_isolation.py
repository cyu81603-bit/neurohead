import copy,time,unittest
from unittest.mock import patch
import numpy as np
import sounddevice
import speech_output
from intent_link import IntentLink

class Session:
    mode='running'
    def __init__(self):self.extra={'life_state':'active','tracking':'coordinated'};self.events=[]
    def life_event(self,event):
        if self.extra['life_state']!='active':raise ValueError('Lifelike mode is not enabled')
        self.events.append(event)

class IsolationTests(unittest.TestCase):
    def play(self,link):
        writes=[];events=[]
        class Stream:
            def __init__(self,**kw):pass
            def __enter__(self):return self
            def __exit__(self,*a):pass
            def write(self,chunk):writes.append(len(chunk));time.sleep(.003)
            def abort(self):pass
        player=speech_output.SpeechOutput(link,lambda k,v:events.append((k,v)))
        with patch.object(speech_output,'synthesize_tts_pcm',return_value=np.full(3200,3000,dtype=np.int16)),patch.object(speech_output,'compute_per_character_amplitudes',return_value=[]),patch.object(sounddevice,'OutputStream',Stream):
            player.speak('你好','笑');player.worker.join(3)
        self.assertFalse(player.worker.is_alive());self.assertEqual(sum(writes),3200)
        self.assertFalse(any(k=='error' for k,v in events),events)
        return events

    def test_audio_plays_when_expression_was_never_enabled(self):
        session=Session();session.extra['life_state']='off';link=IntentLink(session)
        self.play(link);self.assertEqual(session.events,[])
        self.assertEqual(session.extra['tracking'],'coordinated')

    def test_stale_enabled_link_degrades_to_audio_without_enabling_actuators(self):
        session=Session();link=IntentLink(session);link.enable();session.extra['life_state']='off'
        before=copy.deepcopy(session.extra);events=self.play(link)
        self.assertFalse(link.enabled);self.assertEqual(session.events,[])
        self.assertEqual(session.extra,before);self.assertTrue(any(k=='link_warning' for k,v in events))

    def test_shutdown_after_expression_stopped_is_idempotent(self):
        session=Session();link=IntentLink(session);link.enable();link.begin('a','笑',1)
        session.extra['life_state']='off';link.disable();link.disable()
        self.assertIsNone(link.speaking_id);self.assertFalse(link.enabled)

    def test_begin_transport_exception_cannot_abort_audio(self):
        class Broken:
            def begin(self,*a):raise RuntimeError('connection unavailable')
            def end(self,*a):pass
        events=self.play(Broken());self.assertTrue(any(k=='link_warning' for k,v in events))

    def test_energy_transport_exception_cannot_abort_audio(self):
        class Broken:
            def begin(self,*a):return True
            def energy(self,*a):raise RuntimeError('connection unavailable')
            def end(self,*a):pass
        events=self.play(Broken());self.assertTrue(any(k=='link_warning' for k,v in events))

    def test_state_change_between_validation_and_event_does_not_escape(self):
        session=Session();link=IntentLink(session);link.enable()
        def race(event):raise ValueError('Lifelike mode is not enabled')
        session.life_event=race
        self.assertFalse(link.begin('a','笑',1));self.assertFalse(link.enabled)
        link.end('a');self.assertIsNone(link.speaking_id)

if __name__=='__main__':unittest.main()
