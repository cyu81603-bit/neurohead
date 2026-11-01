"""History isolation and fresh inference per turn; no model, audio or hardware IO."""
import json,sys,unittest
from pathlib import Path
from unittest.mock import patch
HERE=Path(__file__).resolve().parent
sys.path[:0]=[str(HERE.parents[1]/'src/pc'),str(HERE)]
from qwen_brain import QwenEmbodiedBrain


class Response:
    def __init__(self,value):self.value=value
    def __enter__(self):return self
    def __exit__(self,*_):pass
    def read(self):return json.dumps({'message':{'content':self.value}}).encode('utf-8')


def packet(reply,actions=None,corrected=''):
    return json.dumps(dict(reply_text=reply,actions=actions or [],expression='无',gaze_mode='track_face',corrected_user_text=corrected,action_reason='本轮请求'),ensure_ascii=False)


class DialogueContextTests(unittest.TestCase):
    def brain(self):
        with patch.object(QwenEmbodiedBrain,'_warmup_worker',lambda self:None):return QwenEmbodiedBrain()

    def test_repeated_words_in_new_topic_always_call_model_with_latest_context(self):
        brain=self.brain();requests=[];plans=[]
        replies=iter([packet('带水和防晒比较合适。'),packet('爬山还要留意天气。'),packet('可以让电脑处理视觉。'),packet('这个分工可以，板卡负责舵机控制。')])
        def infer(req,timeout):
            request=json.loads(req.data)
            if 'actions' in request.get('format',{}).get('properties',{}):
                plans.append(request);return Response(json.dumps(dict(actions=[],wink_request='none',action_reason='无动作')))
            requests.append(request);return Response(next(replies))
        with patch('qwen_brain.urllib.request.urlopen',side_effect=infer):
            brain.infer_multimodal('我准备周末爬山。')
            first=brain.infer_multimodal('你觉得这样可以吗？')
            brain.infer_multimodal('换个话题，电脑跑视觉，板卡控制舵机。')
            second=brain.infer_multimodal('你觉得这样可以吗？')
        self.assertEqual(len(requests),4);self.assertEqual(len(plans),4);self.assertNotEqual(first['reply_text'],second['reply_text'])
        self.assertTrue(all(len(plan['messages'])==2 for plan in plans))
        self.assertIn('电脑跑视觉',json.dumps(requests[-1]['messages'],ensure_ascii=False))
        for req in (requests[1],requests[3]):
            self.assertIn('你觉得这样可以吗',req['messages'][-1]['content'])
            self.assertEqual(req['messages'][0]['role'],'system')
            self.assertEqual(sum(m['role']=='system' for m in req['messages']),1)
        self.assertEqual(len(brain.chat_history),9)
        self.assertTrue(all('动作决策' not in m['content'] and '【听清' not in m['content'] for m in brain.chat_history[1:]))

    def test_previous_left_refusal_and_control_tags_cannot_replace_current_original(self):
        brain=self.brain();brain.chat_history.extend([
            dict(role='user',content='请用左眼wink'),
            dict(role='assistant',content='【听清:请用左眼wink】【表情:无】【动作决策:无】\n左眼会遮挡摄像头。')])
        requests=[]
        def infer(req,timeout):requests.append(json.loads(req.data));return Response(packet('这次眨给你看。',['wink'],'wink一下'))
        with patch('qwen_brain.urllib.request.urlopen',side_effect=infer):r=brain.infer_multimodal('那就wink一下')
        self.assertEqual(r['actions'],['wink'])
        planning=next(r for r in requests if 'actions' in r.get('format',{}).get('properties',{}))
        chat=next(r for r in requests if 'actions' not in r.get('format',{}).get('properties',{}))
        self.assertEqual(len(planning['messages']),2)
        self.assertEqual(chat['messages'][2]['content'],'左眼会遮挡摄像头。')
        self.assertIn('那就wink一下',chat['messages'][-1]['content'])
        self.assertEqual(brain.chat_history[-2]['content'],'那就wink一下')
        self.assertEqual(brain.chat_history[-1]['content'],'这次眨给你看。')

    def test_malformed_json_is_not_spoken_or_reinjected_as_history(self):
        brain=self.brain();before=list(brain.chat_history)
        malformed='{"reply_text":"我正在考虑", "actions": , "analysis":"重复分析"}'
        with patch('qwen_brain.urllib.request.urlopen',return_value=Response(malformed)):r=brain.infer_multimodal('wink')
        self.assertEqual(r['actions'],[]);self.assertEqual(r['backend'],'offline_fallback')
        self.assertEqual(brain.chat_history,before)
        self.assertNotIn('analysis',r['reply_text']);self.assertNotIn('actions',r['reply_text'])

    def test_structured_wink_side_resolves_only_registered_wink_and_preserves_other_actions(self):
        for side,given,expected in (
                ('default',[],['wink']),('right',['smile'],['smile','wink']),
                ('left',['wink'],[]),('left',['wink','smile'],['smile']),('none',['wink'],[])):
            raw=json.dumps(dict(reply_text='回答',wink_request=side,actions=given,action_reason='本轮判断'))
            names,_,error=QwenEmbodiedBrain._parse_action_decision(raw)
            self.assertEqual(names,expected);self.assertIsNone(error)
        for side in ('other',True,{}):
            self.assertTrue(QwenEmbodiedBrain._parse_action_decision(json.dumps(dict(wink_request=side,actions=[])))[2])
        names,_,error=QwenEmbodiedBrain._parse_action_decision(json.dumps(dict(wink_request='right',actions=['head_up','eyes_up','shake_head'])))
        self.assertEqual(names,[]);self.assertTrue(error)

    def test_no_keyword_trigger_and_reply_text_is_never_replaced_by_action_result(self):
        for side,given,reply,expected in (
                ('none',[],'我不会做这个动作。',[]),
                ('left',['wink'],'好的，我眨一下右眼。',[]),
                ('default',[],'左眼不能wink。',['wink'])):
            brain=self.brain();raw=json.dumps(dict(wink_request=side,actions=given,expression='wink',reply_text=reply))
            with patch('qwen_brain.urllib.request.urlopen',return_value=Response(raw)):r=brain.infer_multimodal('wink')
            self.assertEqual(r['actions'],expected)
            self.assertEqual(r['reply_text'],reply)

    def test_failed_fresh_planner_never_reuses_old_wink_but_conversation_can_continue(self):
        brain=self.brain();phase=[0]
        def infer(req,timeout):
            data=json.loads(req.data)
            if 'actions' in data.get('format',{}).get('properties',{}):
                phase[0]+=1
                if phase[0]>1:raise OSError('planner offline')
                return Response(json.dumps(dict(wink_request='default',actions=['wink'],action_reason='本轮wink')))
            return Response(packet('我在听，你继续说。'))
        with patch('qwen_brain.urllib.request.urlopen',side_effect=infer):
            first=brain.infer_multimodal('wink');second=brain.infer_multimodal('我们换个话题')
        self.assertEqual(first['actions'],['wink']);self.assertEqual(second['actions'],[])
        self.assertTrue(second['action_parse_error']);self.assertEqual(second['backend'],'ollama')

    def test_chat_does_not_receive_action_results_or_rewrite_model_words(self):
        brain=self.brain();captured=[]
        def infer(req,timeout):
            data=json.loads(req.data);captured.append(data)
            if 'actions' in data.get('format',{}).get('properties',{}):
                return Response(json.dumps(dict(wink_request='none',actions=['head_up'],action_reason='请求抬头')))
            return Response(packet('我们接着聊刚才的话题吧。'))
        with patch('qwen_brain.urllib.request.urlopen',side_effect=infer):r=brain.infer_multimodal('请抬头')
        self.assertEqual(r['reply_text'],'我们接着聊刚才的话题吧。')
        chat=next(p for p in captured if 'actions' not in p.get('format',{}).get('properties',{}))
        self.assertNotIn('本轮动作已经单独分析',json.dumps(chat,ensure_ascii=False))
        self.assertEqual(r['actions'],['head_up'])

    def test_canceled_reply_is_not_committed_to_memory(self):
        import threading
        brain=self.brain();cancel=threading.Event();before=list(brain.chat_history)
        class Late(Response):
            def read(self):cancel.set();return super().read()
        with patch('qwen_brain.urllib.request.urlopen',return_value=Late(packet('迟到回答'))):
            result=brain.reply_multimodal('上一轮的话',cancelled=cancel.is_set)
        self.assertTrue(result['cancelled']);self.assertEqual(brain.chat_history,before)

    def test_both_routes_use_same_start_snapshot_not_concurrent_reply(self):
        brain=self.brain();brain.chat_history.extend([
            dict(role='user',content='请抬头'),dict(role='assistant',content='换个角度看看。')])
        snapshot=brain.capture_context();captured=[]
        # Even a reply committed before the planner starts cannot leak into
        # the already captured turn or masquerade as another user request.
        with patch('qwen_brain.urllib.request.urlopen',return_value=Response('这轮新回答')):
            brain.reply_multimodal('再来一次',context_snapshot=snapshot)
        def infer(req,timeout):
            captured.append(json.loads(req.data))
            return Response(json.dumps(dict(actions=['head_up'],wink_request='none',action_reason='承接上一请求')))
        with patch('qwen_brain.urllib.request.urlopen',side_effect=infer):
            decision=brain.plan_actions('再来一次',context_snapshot=snapshot)
        context=json.loads(captured[0]['messages'][-1]['content'])
        self.assertEqual(context['current_user_text'],'再来一次')
        self.assertEqual(context['recent_dialogue'][-2]['content'],'请抬头')
        self.assertNotIn('这轮新回答',json.dumps(context,ensure_ascii=False))
        self.assertEqual(decision['actions'],['head_up'])

    def test_capture_context_does_not_wait_for_conversational_model_lock(self):
        import threading
        brain=self.brain();done=threading.Event();snapshots=[]
        with brain._lock:
            worker=threading.Thread(target=lambda:(snapshots.append(brain.capture_context()),done.set()))
            worker.start()
            try:self.assertTrue(done.wait(.5))
            finally:worker.join(.5)
        snapshots[0]['history'].append(dict(role='user',content='不能回写'))
        self.assertEqual(len(brain.chat_history),1)

    def test_canceled_plan_not_remembered_and_clear_erases_both_memories(self):
        import threading
        brain=self.brain();cancel=threading.Event()
        class Late(Response):
            def read(self):cancel.set();return super().read()
        raw=json.dumps(dict(actions=['head_up'],wink_request='none',action_reason='抬头'))
        with patch('qwen_brain.urllib.request.urlopen',return_value=Late(raw)):
            self.assertTrue(brain.plan_actions('抬头',cancelled=cancel.is_set)['cancelled'])
        self.assertEqual(brain.capture_context()['action_intents'],[])
        with patch('qwen_brain.urllib.request.urlopen',return_value=Response(raw)):
            brain.plan_actions('抬头')
        self.assertEqual(brain.capture_context()['action_intents'][0]['status'],'intent_only_execution_unconfirmed')
        brain.clear_history();self.assertEqual(brain.capture_context()['action_intents'],[])

    def test_planner_background_includes_summary_and_intent_but_is_bounded(self):
        brain=self.brain();captured=[]
        snapshot=dict(summary='之前主题是追踪和抬头',
            history=[dict(role='user' if i%2==0 else 'assistant',content='历史很长。'*1000) for i in range(40)],
            action_intents=[dict(user_text='请求抬头。'*1000,actions=['head_up'],wink_request='none') for _ in range(6)])
        def infer(req,timeout):
            captured.append(json.loads(req.data))
            return Response(json.dumps(dict(actions=['head_up'],wink_request='none',action_reason='指代抬头')))
        with patch('qwen_brain.urllib.request.urlopen',side_effect=infer):
            brain.plan_actions('再来一次',context_snapshot=snapshot)
        messages=captured[0]['messages'];context=json.loads(messages[-1]['content'])
        self.assertIn('抬头',context['history_summary'])
        self.assertEqual(context['recent_action_intents'][-1]['actions'],['head_up'])
        self.assertLess(brain.estimate_messages_tokens(messages),brain.context_window_tokens)


if __name__=='__main__':unittest.main()
