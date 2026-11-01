"""Context-aware action planner against local Ollama; no hardware/audio IO."""
import argparse,json,sys,time
from pathlib import Path
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'integration/embodied'),str(ROOT/'src/pc')]
from qwen_brain import QwenEmbodiedBrain


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--live-llm',action='store_true');args=parser.parse_args()
    if not args.live_llm:print('Dry run; --live-llm required');return
    with patch.object(QwenEmbodiedBrain,'_warmup_worker',lambda self:None):brain=QwenEmbodiedBrain()
    cases=[
        ('请抬头','换个角度看看。','再来一次',['head_up']),
        ('请摇头','哈哈，没那么容易说服我。','刚才那个动作再做一遍',['shake_head']),
        ('笑一下','听着就让人开心。','你为什么这么回答？',[]),
        ('请抬眼','我在听呢。','不用再做刚才那个动作了',[]),
        ('请用左眼wink','左眼会遮挡摄像头，不能这样眨。','那就wink一下',['wink']),
        ('请用右眼wink','留意这一下。','再来一次',['wink']),
        ('今天想去散步','走走也挺好。','再来一次',[]),
        ('先摇头然后抬头','我们慢慢来。','不是刚才那个，笑一下',['smile']),
    ]
    rows=[]
    for old,reply,current,expected in cases:
        brain.clear_history()
        brain.chat_history.extend([dict(role='user',content=old),dict(role='assistant',content=reply)])
        result=brain.plan_actions(current,context_snapshot=brain.capture_context())
        row=dict(previous_user=old,previous_reply=reply,current_user=current,expected=expected,
                 **result,passed=result['actions']==expected and not result['action_parse_error'])
        rows.append(row);print(json.dumps(row,ensure_ascii=False),flush=True)
        (ROOT/'build/action_context_llm_check.json').write_text(json.dumps(dict(epoch=time.time(),hardware_io=False,results=rows),ensure_ascii=False,indent=2),encoding='utf-8')
    if not all(r['passed'] for r in rows):raise SystemExit(1)


if __name__=='__main__':main()
