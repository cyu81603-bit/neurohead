"""Read-only local LLM dialogue tests; no microphone, speaker or board control."""
import argparse,json,sys,time
from pathlib import Path
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'integration/embodied'),str(ROOT/'src/pc')]
from qwen_brain import QwenEmbodiedBrain


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--live-llm',action='store_true');args=parser.parse_args()
    if not args.live_llm:print('Dry run: --live-llm required; hardware_io=False');return
    with patch.object(QwenEmbodiedBrain,'_warmup_worker',lambda self:None):brain=QwenEmbodiedBrain()
    rows=[]
    def record(name,text,expected=None,words=(),absent=()):
        result=brain.infer_multimodal(text,timeout=45.);reply=result['reply_text']
        passed=result['backend']=='ollama' and result['actions']==(expected or [])
        passed=passed and (not words or any(w in reply for w in words)) and not any(w in reply for w in absent)
        passed=passed and not any(w in reply for w in ('正在执行','执行指令','调用动作库','系统已识别','正在调整','调整头部角度','我已经','我已'))
        row=dict(name=name,text=text,reply=reply,actions=result['actions'],backend=result['backend'],passed=passed)
        rows.append(row);print(json.dumps(row,ensure_ascii=False),flush=True)
        (ROOT/'build/dialogue_context_llm_check.json').write_text(json.dumps(dict(epoch=time.time(),hardware_io=False,results=rows),ensure_ascii=False,indent=2),encoding='utf-8')
        return reply
    brain.chat_history.extend([dict(role='user',content='周末去爬山，我准备带水、防晒和雨衣。'),dict(role='assistant',content='出发前留意天气和路线。')])
    first=record('repeated-question-hiking','你觉得这样可以吗？',words=('山','水','防晒','雨','天气','路线','装备','充电宝','急救'),absent=('FPGA','舵机'))
    brain.chat_history.extend([dict(role='user',content='现在换个话题，我打算让电脑处理视觉，AX7020板卡只负责舵机控制。'),dict(role='assistant',content='我们现在讨论机器人计算任务的分工。')])
    second=record('same-question-new-topic','你觉得这样可以吗？',words=('视觉','电脑','板卡','舵机','分工','计算'),absent=('爬山','防晒','雨衣'))
    if first==second:rows[-1]['passed']=False
    for text,expected in [('请抬起头',['head_up']),('请摇摇头',['shake_head']),('笑一下',['smile']),('请wink一下',['wink'])]:
        contradictions={'head_up':('点头','低头','眼睛抬','抬眼','不能抬','没法抬','抬头了'),
                        'shake_head':('点头','低头','摇头了'),
                        'smile':('比心','不能笑'),'wink':('左眼','不能眨')}
        brain.clear_history();record('natural-action-reply',text,expected,absent=contradictions[expected[0]])
    brain.clear_history();record('no-invented-arms','你能伸手和我握个手吗？',words=('手','头','身体','胳膊','四肢','颈'))
    brain.clear_history();record('no-invented-vision','你看见我手里拿的什么了吗？',words=('画面','图片','看不','没','无法','摄像头'),absent=('最近几秒','画面里','捕捉到'))
    (ROOT/'build/dialogue_context_llm_check.json').write_text(json.dumps(dict(epoch=time.time(),hardware_io=False,results=rows),ensure_ascii=False,indent=2),encoding='utf-8')
    if not all(r['passed'] for r in rows):raise SystemExit(1)


if __name__=='__main__':main()
