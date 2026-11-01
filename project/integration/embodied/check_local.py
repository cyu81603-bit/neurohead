"""Real local dependencies, ASR and LLM validation, no camera/mic/audio output/UDP."""
import argparse
import hashlib
import json
import sys
import time
import urllib.request
from pathlib import Path

HERE=Path(__file__).resolve().parent
sys.path.insert(0,str(HERE))


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--llm',action='store_true');args=parser.parse_args()
    import config,numpy as np
    from tts_lip_sync import synthesize_tts_pcm,compute_per_character_amplitudes
    from audio_asr import VoiceASREngine
    report={'hardware_commands_sent':0,'camera_opened':False,'microphone_opened':False,'audio_played':False}
    with urllib.request.urlopen('http://127.0.0.1:11434/api/tags',timeout=5) as res:tags=json.load(res)
    report['ollama_models']=[m['name'] for m in tags['models']]
    assert config.OLLAMA_MODEL in report['ollama_models']
    assert config.OLLAMA_EXE.is_file()
    pcm=synthesize_tts_pcm('你好，我是机器人，很高兴见到你。')
    assert len(pcm)>1600,'SAPI failed'
    report['tts_pcm_seconds']=len(pcm)/16000
    report['tts_characters']=len(compute_per_character_amplitudes('你好，我是机器人，很高兴见到你。',pcm))
    asr=VoiceASREngine();assert asr._ensure_sensevoice_loaded()
    stream=asr._sensevoice_recognizer.create_stream()
    stream.accept_waveform(16000,pcm.astype(np.float32)/32768)
    asr._sensevoice_recognizer.decode_stream(stream)
    report['asr_recognized_synthesized_speech']=stream.result.text
    assert stream.result.text,'ASR did not recognize synthesized speech'
    report['asr_model_sha256']=hashlib.sha256(config.SENSEVOICE_MODEL_PATH.read_bytes()).hexdigest()
    if args.llm:
        from qwen_brain import QwenEmbodiedBrain
        brain=QwenEmbodiedBrain()
        before=time.monotonic()
        reply=brain.infer_multimodal('我们已经让机器人眼睛和脖子顺畅追踪了，请简短地祝贺我们。',None,{})
        assert reply.get('backend')=='ollama','Ollama failed, fallback is not acceptance'
        assert reply['reply_text']
        report['llm']={k:reply[k] for k in ('backend','reply_text','expression','latency_ms','video_attached')}
    out=HERE/'build/local_check.json';out.parent.mkdir(exist_ok=True)
    out.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(report,ensure_ascii=False,indent=2))


if __name__=='__main__':main()
