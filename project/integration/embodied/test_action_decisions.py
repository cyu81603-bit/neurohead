"""LLM contract, dispatch dedup and cancellation; no live model or hardware."""
import json,sys,threading,types,unittest
from pathlib import Path
from unittest.mock import patch
HERE=Path(__file__).resolve().parent
sys.path[:0]=[str(HERE.parents[1]/'src/pc'),str(HERE)]
from action_library import ACTION_NAMES
from qwen_brain import QwenEmbodiedBrain
from intent_link import IntentLink,expression_name
from embodied_app import BrainPanel


class DecisionTests(unittest.TestCase):
    def test_right_wink_aliases_and_left_side_rejected(self):
        self.assertEqual(expression_name('右眼wink'),'wink');self.assertEqual(expression_name('wink_right'),'wink')
        for name in ('wink_left','左眼wink'):
            with self.assertRaises(ValueError):expression_name(name)
    def test_structured_registered_actions_and_empty_conversation(self):
        for names in ([],['head_up'],['wink'],['eyes_up'],['shake_head'],['smile'],['sad'],['smile','head_up']):
            raw=json.dumps(dict(actions=names,action_reason='当前用户请求',reply_text='我理解你的请求。'))
            chosen,reason,error=QwenEmbodiedBrain._parse_action_decision(raw)
            self.assertEqual(chosen,names);self.assertIsNone(error)
        for value in ('head_up',['raw_pwm'],['head_up']*4,[{'name':'head_up','us':2000}]):
            actions,_,error=QwenEmbodiedBrain._parse_action_decision(json.dumps({'actions':value}))
            self.assertEqual(actions,[]);self.assertTrue(error)
        self.assertEqual(QwenEmbodiedBrain._parse_action_decision('{"reply_text":"旧接口"}')[0],[])

    def test_actual_inference_contract_passes_actions_and_has_no_keyword_execution(self):
        captured=[]
        class Response:
            def __enter__(self):return self
            def __exit__(self,*a):pass
            def read(self):return json.dumps(dict(message=dict(content=json.dumps(dict(reply_text='我会尝试抬头。',corrected_user_text='请抬头',expression='无',gaze_mode='track_face',actions=['head_up'],action_reason='明确请求'))))).encode()
        with patch.object(QwenEmbodiedBrain,'_warmup_worker',lambda self:None):brain=QwenEmbodiedBrain()
        def respond(req,timeout):captured.append(json.loads(req.data));return Response()
        with patch('qwen_brain.urllib.request.urlopen',side_effect=respond):result=brain.infer_multimodal('请抬头')
        self.assertEqual(result['actions'],['head_up']);self.assertEqual(result['backend'],'ollama')
        planning=next(p for p in captured if 'actions' in p.get('format',{}).get('properties',{}))
        self.assertIn('actions',planning['format']['required'])
        self.assertEqual(set(planning['format']['properties']['actions']['items']['enum']),set(ACTION_NAMES))
        with patch('qwen_brain.urllib.request.urlopen',side_effect=OSError('offline')):result=brain.infer_multimodal('请你摇摇头')
        self.assertEqual(result['actions'],[]);self.assertEqual(result['backend'],'offline_fallback')

    def test_dispatch_checks_library_independently_and_audio_keeps_pose(self):
        events=[];session=types.SimpleNamespace(mode='running',extra={'action_library_enabled':False,'life_state':'active'},life_event=lambda event:events.append(event))
        link=IntentLink(session)
        self.assertEqual(link.dispatch_actions(['head_up'],'x')['status'],'rejected');self.assertEqual(events,[])
        session.extra['action_library_enabled']=True
        self.assertEqual(link.dispatch_actions(['head_up'],'x')['status'],'accepted')
        self.assertEqual(events[-1],dict(type='action',request_id='x',actions=['head_up']))
        link.enable();self.assertTrue(link.begin('speech','keep',2));self.assertEqual(len(events),1)
        link.energy('speech',.8);self.assertEqual(events[-1]['type'],'speech.energy')
        link.cancel_actions();self.assertEqual(events[-1],dict(type='action.cancel',request_id='x'))

    def test_ui_dispatches_once_independently_and_interrupt_cancels_own_request(self):
        events=[];sent=[]
        result=dict(reply_text='好的。',expression='笑',actions=['smile'],action_reason='请求微笑')
        panel=types.SimpleNamespace(brain=types.SimpleNamespace(reply_multimodal=lambda *a,**k:dict(result),plan_actions=lambda *a,**k:dict(result),capture_context=lambda:dict(history=[],summary="",action_intents=[])),
            query_lock=threading.Lock(),intent_generation_lock=threading.RLock(),generation=0,closed=threading.Event(),
            buffer=types.SimpleNamespace(extract_speech_video=lambda *a:None,on_speech_cancel=lambda:None),frame=None,vision={},
            event=lambda *a:events.append(a),voice=None)
        session=types.SimpleNamespace(mode='running',extra={'action_library_enabled':True},life_event=lambda e:sent.append(e))
        panel.link=IntentLink(session);panel.speech=types.SimpleNamespace(speak=lambda *a:sent.append(('speech',a)),stop=lambda:None)
        BrainPanel.query(panel,'请你笑一下',0,1)
        self.assertEqual(sum(isinstance(e,dict) and e.get('type')=='action' for e in sent),1)
        self.assertIn(('speech',('好的。','keep')),sent)
        BrainPanel.interrupt_worker(panel);self.assertEqual(sent[-1]['type'],'action.cancel')

    def test_interrupted_pending_model_answer_never_dispatches_motion(self):
        sent=[];panel=types.SimpleNamespace(query_lock=threading.Lock(),intent_generation_lock=threading.RLock(),generation=0,closed=threading.Event(),
            buffer=types.SimpleNamespace(extract_speech_video=lambda *a:None),frame=None,vision={},event=lambda *a:None)
        ready=threading.Event()
        def reply(*args,**kwargs):panel.generation+=1;ready.set();return dict(reply_text='好的。',expression=None)
        def plan(*args,**kwargs):ready.wait(1);return dict(actions=['head_up'])
        panel.brain=types.SimpleNamespace(reply_multimodal=reply,plan_actions=plan,capture_context=lambda:dict(history=[],summary="",action_intents=[]));panel.link=types.SimpleNamespace(dispatch_actions=lambda *a:sent.append(a))
        panel.speech=types.SimpleNamespace(speak=lambda *a:sent.append(a))
        BrainPanel.query(panel,'请抬头',0,1);self.assertEqual(sent,[])


if __name__=='__main__':unittest.main()
