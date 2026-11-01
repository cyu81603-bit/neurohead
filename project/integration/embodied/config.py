"""Local voice/VLM settings. Hardware calibration belongs exclusively to NH22."""
import os
from pathlib import Path

for key in ('OPENBLAS_NUM_THREADS','OMP_NUM_THREADS','MKL_NUM_THREADS'):
    os.environ[key]='1'
WORKSPACE_ROOT=Path(__file__).resolve().parent
PROJECT_ROOT=WORKSPACE_ROOT.parents[1]
BUILD_OUTPUT_DIR=WORKSPACE_ROOT/'build'
BUILD_OUTPUT_DIR.mkdir(parents=True,exist_ok=True)
OLLAMA_EXE=Path(r'F:\Ollama\ollama.exe')
OLLAMA_MODELS_DIR=Path(r'F:\Ollama\models')
OLLAMA_CHAT_URL='http://127.0.0.1:11434/api/chat'
OLLAMA_GENERATE_URL='http://127.0.0.1:11434/api/generate'
OLLAMA_MODEL='qwen3.5:4b'
OLLAMA_KEEP_ALIVE='60m'
LLM_TIMEOUT_S=45.
LLM_CONTEXT_WINDOW_TOKENS=4096
LLM_COMPRESS_THRESHOLD_TOKENS=3072
LLM_KEEP_RECENT_MESSAGES=8
ALLOWED_EXPRESSIONS=('笑','难过','wink')
SILENT_RETENTION_SECONDS=5.
PRE_SPEECH_LOOKBACK_SECONDS=5.
VLM_STORYBOARD_FRAMES=6
VLM_GRID_TILE_W=240
VLM_GRID_TILE_H=180
# No numeric-index camera fallback; the integrated UI only reads shared frames.
CAMERA_INDEX='USB Cam'
FRAME_WIDTH=640
FRAME_HEIGHT=480
CAMERA_FPS=15
SENSEVOICE_MODEL_DIR=WORKSPACE_ROOT/'models/sensevoice_small_int8'
SENSEVOICE_MODEL_PATH=SENSEVOICE_MODEL_DIR/'model.int8.onnx'
SENSEVOICE_TOKENS_PATH=SENSEVOICE_MODEL_DIR/'tokens.txt'
SENSEVOICE_NUM_THREADS=6
AUDIO_SAMPLE_RATE=16000
TTS_SAMPLE_RATE=16000
VAD_ENERGY_THRESHOLD=11.
VAD_MIN_P90_SPEECH_RMS=12.
VAD_START_CONSECUTIVE_FRAMES=2
VAD_MIN_VOICED_RATIO=.12
VAD_MIN_VOICE_BAND_RATIO=.20
VAD_SILENCE_DURATION_S=.60
VAD_MIN_SPEECH_S=.30
VAD_MAX_SPEECH_S=15.
VAD_PRE_ROLL_SECONDS=.65
# Compatibility metadata consumed by the imported character-analysis function.
# This value is never sent as a servo target: speech output uses energy only.
FACE_CHANNEL_CONFIG={'jaw_mouth':dict(channel=21,neutral_us=1500,min_us=1500,
    max_us=1500,max_open_delta_us=0)}
