"""Local-model wink-side regression. Never connects to a board or dispatches actions."""
import argparse,json,sys,time
from pathlib import Path
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'integration/embodied'),str(ROOT/'src/pc')]
from qwen_brain import QwenEmbodiedBrain


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--live-llm',action='store_true');args=parser.parse_args()
    cases=[('wink',['wink'],'right'),('请你做一个wink',['wink'],'right'),
           ('wink一下',['wink'],'right'),('眨一只眼',['wink'],'right'),
           ('请用右眼wink',['wink'],'right'),('请用左眼wink',[],'left'),
           ('用左眼眨一下',[],'left'),('不要wink',[],'none'),
           ('wink是什么意思？',[],'none'),('不要左眼，用右眼wink',['wink'],'right'),
           ('你刚说左眼不能wink，那就wink一下',['wink'],'right'),
           ('别wink，笑一下',['smile'],'none')]
    if not args.live_llm:
        print(json.dumps(dict(hardware_io=False,dry_run=True,cases=cases),ensure_ascii=False));return
    with patch.object(QwenEmbodiedBrain,'_warmup_worker',lambda self:None):brain=QwenEmbodiedBrain()
    rows=[]
    def check(text,expected,side,history_case=False):
        result=brain.infer_multimodal(text,timeout=45.)
        reply=result['reply_text']
        side_ok=('左眼' not in reply and 'left eye' not in reply.lower()) if side=='right' else (
            '左眼' in reply and any(w in reply for w in ('遮','挡','不能','没法','无法','不支持')) if side=='left' else True)
        style_ok=not expected or not any(word in reply for word in ('执行指令','正在执行','调用动作库','系统已识别'))
        row=dict(text=text,expected=expected,actions=result['actions'],reply=reply,reason=result['action_reason'],
                 backend=result['backend'],history_case=history_case,
                 action_passed=result['actions']==expected and not result.get('action_parse_error'),
                 spoken_side_passed=side_ok,
                 passed=result['backend']=='ollama' and result['actions']==expected and side_ok and style_ok,
                 latency_ms=result['latency_ms'])
        rows.append(row)
        (ROOT/'build/wink_default_right_llm_check.json').write_text(json.dumps(dict(epoch=time.time(),hardware_io=False,results=rows),ensure_ascii=False,indent=2),encoding='utf-8')
        print(json.dumps(row,ensure_ascii=False),flush=True)
    for text,expected,side in cases:
        brain.clear_history();check(text,expected,side)
    brain.clear_history()
    check('请用左眼wink',[],'left',True)
    check('那就wink一下',['wink'],'right',True)
    if not all(r['passed'] for r in rows):raise SystemExit(1)


if __name__=='__main__':main()
