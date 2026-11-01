"""Measure concurrent local-model routes; results never reach hardware or audio."""
import argparse,json,sys,time,threading
from pathlib import Path
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'integration/embodied'),str(ROOT/'src/pc')]
from qwen_brain import QwenEmbodiedBrain
from parallel_turn import turn_results


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--live-llm',action='store_true');args=parser.parse_args()
    if not args.live_llm:print('Dry run; --live-llm required');return
    with patch.object(QwenEmbodiedBrain,'_warmup_worker',lambda self:None):brain=QwenEmbodiedBrain()
    cases=[('这段程序终于跑通了，你觉得下一步该验证什么？顺便抬一下头。',['head_up']),
           ('今天天气晴朗，我想出去走走，你觉得呢？顺便wink一下。',['wink'])]
    rows=[]
    for text,expected in cases:
        brain.clear_history();start=time.monotonic();times={};results={};order=[]
        snapshot=brain.capture_context()
        def call(name,fn):
            times[name]={'start':time.monotonic()-start}
            try:return fn()
            finally:times[name]['end']=time.monotonic()-start
        for kind,result,error in turn_results(lambda:call('reply',lambda:brain.reply_multimodal(text,context_snapshot=snapshot)),lambda:call('action',lambda:brain.plan_actions(text,context_snapshot=snapshot))):
            if error:raise error
            results[kind]=result;order.append(dict(route=kind,available_s=round(time.monotonic()-start,3)))
        overlap=max(v['start'] for v in times.values())<min(v['end'] for v in times.values())
        passed=overlap and results['action_decision']['actions']==expected and results['reply']['backend']=='ollama'
        reply=results['reply']['reply_text']
        passed=passed and not any(s in reply for s in ('正在执行','执行指令','调用动作库','正在调整','没法帮你抬头','只能看到','抬起了头','我已经','收到你的指令'))
        if expected==['wink']:passed=passed and not any(s in reply for s in ('奇怪','还是保持微笑','不能wink','没法wink'))
        row=dict(text=text,expected=expected,actions=results['action_decision']['actions'],reply=reply,
                 request_intervals=times,completion_order=order,requests_overlapped=overlap,
                 server_compute_parallelism_proven=False,passed=passed)
        rows.append(row);print(json.dumps(row,ensure_ascii=False),flush=True)
        (ROOT/'build/parallel_dialogue_llm_check.json').write_text(json.dumps(dict(epoch=time.time(),hardware_io=False,results=rows),ensure_ascii=False,indent=2),encoding='utf-8')
    if not all(r['passed'] for r in rows):raise SystemExit(1)


if __name__=='__main__':main()
