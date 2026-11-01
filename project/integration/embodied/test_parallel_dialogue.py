"""Route completion order, failures and cancellation; no live IO."""
import threading,types,time,unittest
from embodied_app import BrainPanel
from intent_link import IntentLink


class ParallelDialogueTests(unittest.TestCase):
    def panel(self,reply,plan):
        self.sent=[];self.events=[];self.spoken=threading.Event();self.dispatched=threading.Event()
        def send(event):self.sent.append(event);self.dispatched.set();return dict(accepted=True)
        session=types.SimpleNamespace(mode='running',extra={'action_library_enabled':True},life_event=send)
        panel=types.SimpleNamespace(brain=types.SimpleNamespace(reply_multimodal=reply,plan_actions=plan,capture_context=lambda:dict(history=[],summary="",action_intents=[])),
            query_lock=threading.Lock(),intent_generation_lock=threading.RLock(),generation=0,closed=threading.Event(),
            buffer=types.SimpleNamespace(extract_speech_video=lambda *a:None,on_speech_cancel=lambda:None),frame=None,vision={},voice=None,
            event=lambda *a:self.events.append(a),link=IntentLink(session))
        def speak(*args):self.sent.append(('speech',args));self.spoken.set()
        panel.speech=types.SimpleNamespace(speak=speak,stop=lambda:self.sent.append('stop'))
        return panel

    def run_query(self,panel):
        worker=threading.Thread(target=BrainPanel.query,args=(panel,'你觉得呢，顺便wink一下',0,1))
        worker.start();return worker

    def test_reply_speaks_before_slow_planner_without_repeating_it_later(self):
        release=threading.Event();entered=threading.Event()
        def plan(*_,**kwargs):entered.set();release.wait(2);return dict(actions=['wink'],action_reason='请求wink')
        p=self.panel(lambda *a,**k:dict(reply_text='刚才那个想法挺有意思。'),plan)
        worker=self.run_query(p)
        try:
            self.assertTrue(entered.wait(1));self.assertTrue(self.spoken.wait(1))
            self.assertFalse(any(isinstance(e,dict) and e.get('type')=='action' for e in self.sent))
        finally:release.set();worker.join(2)
        self.assertFalse(worker.is_alive())
        self.assertEqual(sum(isinstance(e,tuple) and e[0]=='speech' for e in self.sent),1)
        self.assertEqual(sum(isinstance(e,dict) and e.get('type')=='action' for e in self.sent),1)
        self.assertEqual({e[0] for e in self.events if e[0] in ('reply','action_decision')},{'reply','action_decision'})

    def test_fast_planner_dispatches_without_waiting_for_chat(self):
        release=threading.Event()
        def reply(*a,**k):release.wait(2);return dict(reply_text='我们继续聊吧。')
        p=self.panel(reply,lambda *_,**kwargs:dict(actions=['head_up']))
        worker=self.run_query(p)
        try:self.assertTrue(self.dispatched.wait(1));self.assertFalse(self.spoken.is_set())
        finally:release.set();worker.join(2)
        self.assertTrue(self.spoken.is_set())

    def test_chat_failure_does_not_suppress_valid_action(self):
        def fail(*a,**k):raise OSError('chat failed')
        p=self.panel(fail,lambda *_,**kwargs:dict(actions=['wink']))
        BrainPanel.query(p,'wink',0,1)
        self.assertTrue(self.dispatched.is_set());self.assertFalse(self.spoken.is_set())
        self.assertTrue(any(e[0]=='error' for e in self.events))

    def test_planner_failure_does_not_suppress_chat_or_start_action(self):
        def fail(*a,**kwargs):raise OSError('planner failed')
        p=self.panel(lambda *a,**k:dict(reply_text='我在听。'),fail)
        BrainPanel.query(p,'你好',0,1)
        self.assertTrue(self.spoken.is_set());self.assertFalse(self.dispatched.is_set())

    def test_interrupt_releases_query_without_late_speech_or_motion(self):
        release=threading.Event();reply_entered=threading.Event();plan_entered=threading.Event()
        def reply(*a,**k):reply_entered.set();release.wait(2);return dict(reply_text='迟到回答')
        def plan(*a,**kwargs):plan_entered.set();release.wait(2);return dict(actions=['wink'])
        p=self.panel(reply,plan);worker=self.run_query(p)
        try:
            self.assertTrue(reply_entered.wait(1));self.assertTrue(plan_entered.wait(1))
            BrainPanel.interrupt_worker(p);worker.join(.5)
            self.assertFalse(worker.is_alive());self.assertFalse(p.query_lock.locked())
        finally:release.set();worker.join(2)
        self.assertFalse(self.spoken.is_set());self.assertFalse(self.dispatched.is_set())

    def test_interruption_after_fast_action_cancels_it_and_discards_late_reply(self):
        release=threading.Event()
        def reply(*a,**k):release.wait(2);return dict(reply_text='迟到回答')
        p=self.panel(reply,lambda *_,**kwargs:dict(actions=['wink']));worker=self.run_query(p)
        try:
            self.assertTrue(self.dispatched.wait(1));BrainPanel.interrupt_worker(p);worker.join(.5)
            self.assertTrue(any(isinstance(e,dict) and e.get('type')=='action.cancel' for e in self.sent))
        finally:release.set();worker.join(2)
        self.assertFalse(self.spoken.is_set())

    def test_ui_captures_once_and_passes_same_context_to_both_routes(self):
        captured=[];seen=[];snapshot={'history':[{'role':'user','content':'请抬头'}]}
        def reply(*a,**k):seen.append(k['context_snapshot']);return dict(reply_text='再看看。')
        def plan(*a,**k):seen.append(k['context_snapshot']);return dict(actions=['head_up'])
        p=self.panel(reply,plan)
        def capture():captured.append(1);return snapshot
        p.brain.capture_context=capture
        BrainPanel.query(p,'再来一次',0,1)
        self.assertEqual(len(captured),1);self.assertEqual(len(seen),2)
        self.assertTrue(all(s is snapshot for s in seen))


if __name__=='__main__':unittest.main()
