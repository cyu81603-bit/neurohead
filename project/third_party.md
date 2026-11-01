# 第三方来源与再分发边界

1. vendor/neurohead_vision包含原项目视觉支持源码；YuNet位于data/models，附yunet_license.txt、readme.md与来源清单，保留原许可。
2. integration/embodied/models/sensevoice_small_int8为现用SenseVoice-Small INT8 ONNX与tokens。来源：sherpa-onnx SenseVoice模型资产（模型本体源自FunAudioLLM/SenseVoiceSmall）。现本地handoff未附该转换文件的独立许可/下载校验来源，须在公开仓库发布前核实对应发行包授权；本包如实保留来源待核查，不自动授予模型权利。
3. support/bsp为Xilinx/AMD Vitis2022.2配套Cortex-A9/lwIP BSP，源码头部版权保留；lwIP等组件适用各自许可。商业工具链本体未包含。源码路径文件名为满足指南转为小写，data/path_case_map.json保留原名映射；原BSP编译产物未修改。
4. Ollama/qwen3.5:4b权重未包含；由接收者按模型发行许可安装。原同学的语义界面和应用源码保留原注释，不冒称全部由本次撰写。
5. 原创部分的开源协议由团队确认后添加；本次不擅自把全包标为MIT。报告未制作，未上传任何公共站点。
