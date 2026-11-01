"""Opt-in local LLM decision checks. Never imports a board client or sends actions."""
import argparse,json,sys,time
from pathlib import Path
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'integration/embodied'),str(ROOT/'src/pc')]
from qwen_brain import QwenEmbodiedBrain


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--live-llm',action='store_true');args=parser.parse_args()
    cases=[('请你抬起头',['head_up']),('请你做一个wink',['wink']),('请你抬一下眼',['eyes_up']),
           ('请你摇摇头',['shake_head']),('请你笑一下',['smile']),('请你做出难过的表情',['sad']),
           ('不要摇头，也不要笑',[]),('wink是什么意思？',[]),('如果我让你抬头，你会怎样？',[]),
           ('你好，介绍一下自己',[])]
    if not args.live_llm:
        print(json.dumps(dict(dry_run=True,cases=cases,hardware_io=False),ensure_ascii=False));return
    with patch.object(QwenEmbodiedBrain,'_warmup_worker',lambda self:None):brain=QwenEmbodiedBrain()
    rows=[]
    for text,expected in cases:
        brain.clear_history()
        result=brain.infer_multimodal(text,timeout=45.)
        row=dict(text=text,expected=expected,actions=result['actions'],backend=result['backend'],
                 passed=result['backend']=='ollama' and result['actions']==expected,
                 reason=result['action_reason'],latency_ms=result['latency_ms'])
        rows.append(row);print(json.dumps(row,ensure_ascii=False),flush=True)
        (ROOT/'build/action_library_llm_check.json').write_text(json.dumps(dict(epoch=time.time(),hardware_io=False,results=rows),ensure_ascii=False,indent=2),encoding='utf-8')
    if not all(r['passed'] for r in rows):raise SystemExit(1)


if __name__=='__main__':main()
