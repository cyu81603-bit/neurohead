"""Original teammate three-column layout, preserved from the handoff.
Only the declarative UI builder is reused; no original hardware scheduler is imported.
"""
import tkinter as tk
import customtkinter as ctk
import config as up_config
NH22_CHANNEL_COUNT=22
class TeammateLayout:
    def _build_ui(self) -> None:
        self.grid_columnconfigure(0, weight=4)
        self.grid_columnconfigure(1, weight=5)
        self.grid_columnconfigure(2, weight=5)
        self.grid_rowconfigure(1, weight=1)

        # ==================== 顶部全局导航与硬件连接横幅 ====================
        header_bar = ctk.CTkFrame(self, height=50, corner_radius=8, fg_color="#141E28")
        header_bar.grid(row=0, column=0, columnspan=3, sticky="ew", padx=10, pady=(8, 4))

        ctk.CTkLabel(
            header_bar,
            text="具身智能全链路主控台 · SenseVoice / Qwen / NH22",
            font=ctk.CTkFont(size=16, weight="bold"),
            text_color="#4FC3F7",
        ).pack(side="left", padx=12, pady=8)

        self.lbl_mask_badge = ctk.CTkLabel(
            header_bar,
            text="NH22 掩码: 0x1C3FBF | 帧: 0",
            font=ctk.CTkFont(family="Consolas", size=12, weight="bold"),
            text_color="#81C784",
            fg_color="#1E2D24",
            corner_radius=6,
            padx=10,
            pady=4,
        )
        self.lbl_mask_badge.pack(side="right", padx=8)

        self.sw_http_bridge = ctk.CTkSwitch(
            header_bar,
            text="转发队友 127.0.0.1:8765",
            command=self._on_toggle_http_bridge,
            font=ctk.CTkFont(size=12),
        )
        self.sw_http_bridge.pack(side="right", padx=8)

        self.sw_hw_udp = ctk.CTkSwitch(
            header_bar,
            text="🔌 直连板卡 UDP (192.168.10.20:5005)",
            command=self._on_toggle_hw_udp,
            font=ctk.CTkFont(size=12, weight="bold"),
            progress_color="#00E676",
        )
        self.sw_hw_udp.pack(side="right", padx=10)

        # ==================== 左栏：常开视觉、YuNet 追踪与 5 秒动态视频池 ====================
        left_panel = ctk.CTkFrame(self, corner_radius=10)
        left_panel.grid(row=1, column=0, padx=(10, 5), pady=6, sticky="nsew")
        left_panel.grid_rowconfigure(1, weight=3)
        left_panel.grid_rowconfigure(3, weight=2)
        left_panel.grid_columnconfigure(0, weight=1)

        top_v_bar = ctk.CTkFrame(left_panel, fg_color="transparent")
        top_v_bar.grid(row=0, column=0, padx=10, pady=(8, 4), sticky="ew")
        ctk.CTkLabel(
            top_v_bar,
            text="1. 常开视觉 & YuNet 追踪视窗",
            font=ctk.CTkFont(size=14, weight="bold"),
            text_color="#80DEEA",
        ).pack(side="left")

        self.lbl_buffer_badge = ctk.CTkLabel(
            top_v_bar,
            text="视频池: 静默保留 5.0s",
            font=ctk.CTkFont(size=11, weight="bold"),
            text_color="#00E5FF",
            fg_color="#162836",
            corner_radius=6,
            padx=8,
            pady=2,
        )
        self.lbl_buffer_badge.pack(side="right")

        self.video_frame_box = ctk.CTkFrame(left_panel, corner_radius=8, fg_color="#0E1014")
        self.video_frame_box.grid(row=1, column=0, padx=10, pady=4, sticky="nsew")
        self.video_frame_box.pack_propagate(False)
        self.lbl_live_video = tk.Label(
            self.video_frame_box,
            bg="#0E1014",
            fg="#90A4AE",
            text="正在启动常开摄像头与队友 YuNet 追踪引擎...",
        )
        self.lbl_live_video.pack(fill="both", expand=True)

        buf_info_frame = ctk.CTkFrame(left_panel, corner_radius=8, fg_color="#161B22")
        buf_info_frame.grid(row=2, column=0, padx=10, pady=4, sticky="ew")
        buf_info_frame.grid_columnconfigure(1, weight=1)

        self.lbl_buf_detail = ctk.CTkLabel(
            buf_info_frame,
            text="静默滚动窗口: 0.0s / 5.0s (旧帧自动清理)",
            font=ctk.CTkFont(size=11),
            text_color="#80DEEA",
        )
        self.lbl_buf_detail.grid(row=0, column=0, padx=8, pady=5, sticky="w")

        self.bar_buffer_span = ctk.CTkProgressBar(buf_info_frame, height=10)
        self.bar_buffer_span.grid(row=0, column=1, padx=8, pady=5, sticky="ew")
        self.bar_buffer_span.set(0.0)

        sb_box = ctk.CTkFrame(left_panel, corner_radius=8, fg_color="#12151C")
        sb_box.grid(row=3, column=0, padx=10, pady=(4, 10), sticky="nsew")
        sb_box.grid_rowconfigure(1, weight=1)
        sb_box.grid_columnconfigure(0, weight=1)

        self.lbl_storyboard_title = ctk.CTkLabel(
            sb_box,
            text="送入 Qwen3.5 的 [开口前5秒 ~ 说话结束] 时序切片 (3x2):",
            font=ctk.CTkFont(size=11, weight="bold"),
            text_color="#B39DDB",
        )
        self.lbl_storyboard_title.grid(row=0, column=0, padx=8, pady=(5, 2), sticky="w")

        self.lbl_storyboard_img = tk.Label(
            sb_box,
            bg="#12151C",
            fg="#607D8B",
            text="说话或提问时自动截取前5秒至说话结束的视频关键帧",
        )
        self.lbl_storyboard_img.grid(row=1, column=0, padx=6, pady=(2, 6), sticky="nsew")

        # ==================== 中栏：语音大模型交互 + 表情控制转换包络 + 逐字嘴形表 ====================
        mid_panel = ctk.CTkFrame(self, corner_radius=10)
        mid_panel.grid(row=1, column=1, padx=5, pady=6, sticky="nsew")
        mid_panel.grid_rowconfigure(2, weight=3)
        mid_panel.grid_rowconfigure(3, weight=2)
        mid_panel.grid_columnconfigure(0, weight=1)

        # ---- 中栏卡片 1：语音交互 & Qwen3.5 大脑 & 零延迟动作自检 ----
        qa_card = ctk.CTkFrame(mid_panel, corner_radius=8, fg_color="#1A202C")
        qa_card.grid(row=0, column=0, padx=8, pady=(8, 4), sticky="ew")
        qa_card.grid_columnconfigure(0, weight=1)

        qa_header = ctk.CTkFrame(qa_card, fg_color="transparent")
        qa_header.pack(fill="x", padx=8, pady=(6, 2))

        self.btn_mic_toggle = ctk.CTkButton(
            qa_header,
            text="🎙️ 语音监听: 开启",
            width=112,
            height=25,
            fg_color="#00695C",
            hover_color="#004D40",
            command=self._toggle_mic,
        )
        self.btn_mic_toggle.pack(side="right", padx=2)

        self.btn_stop_tts = ctk.CTkButton(
            qa_header,
            text="🛑 打断(Esc)",
            width=86,
            height=25,
            fg_color="#C62828",
            hover_color="#B71C1C",
            command=lambda: self._interrupt_all("手动点击打断"),
        )
        self.btn_stop_tts.pack(side="right", padx=2)

        self.btn_clear_ctx = ctk.CTkButton(
            qa_header,
            text="🧹 清空记忆",
            width=82,
            height=25,
            fg_color="#6A1B9A",
            hover_color="#4A148C",
            command=self._clear_brain_context,
        )
        self.btn_clear_ctx.pack(side="right", padx=2)

        ctk.CTkLabel(
            qa_header,
            text="2. 语音交互 & Qwen3.5 大脑",
            font=ctk.CTkFont(size=13, weight="bold"),
            text_color="#A5D6A7",
        ).pack(side="left")

        self.lbl_ctx_badge = ctk.CTkLabel(
            qa_header,
            text="上下文: 0.4k/64k",
            font=ctk.CTkFont(family="Consolas", size=11),
            text_color="#B39DDB",
            fg_color="#232B3A",
            corner_radius=5,
            padx=6,
            pady=1,
        )
        self.lbl_ctx_badge.pack(side="left", padx=6)

        self.lbl_asr_status = ctk.CTkLabel(
            qa_card,
            text="🎙️ 正在初始化离线 SenseVoice-Small (INT8) 与麦克风流...",
            font=ctk.CTkFont(size=11),
            text_color="#80CBC4",
        )
        self.lbl_asr_status.pack(anchor="w", padx=10, pady=(0, 2))

        noise_row = ctk.CTkFrame(qa_card, fg_color="#131822", corner_radius=6)
        noise_row.pack(fill="x", padx=8, pady=2)
        noise_row.grid_columnconfigure(1, weight=1)

        self.lbl_noise_gate = ctk.CTkLabel(
            noise_row,
            text=f"🛡️ 杂音门限(P90>={int(up_config.VAD_MIN_P90_SPEECH_RMS)}):",
            font=ctk.CTkFont(size=11, weight="bold"),
            text_color="#80DEEA",
            width=155,
            anchor="w",
        )
        self.lbl_noise_gate.grid(row=0, column=0, padx=(6, 2), pady=3, sticky="w")

        self.slider_noise_gate = ctk.CTkSlider(
            noise_row,
            from_=5,
            to=125,
            number_of_steps=60,
            height=13,
            command=self._on_noise_gate_slider_change,
        )
        self.slider_noise_gate.set(up_config.VAD_MIN_P90_SPEECH_RMS)
        self.slider_noise_gate.grid(row=0, column=1, padx=4, pady=3, sticky="ew")

        self.lbl_mic_rms = ctk.CTkLabel(
            noise_row,
            text="音量: 0 | 底噪: 1 | 滤噪: 0",
            font=ctk.CTkFont(family="Consolas", size=11),
            text_color="#90A4AE",
            width=195,
            anchor="e",
        )
        self.lbl_mic_rms.grid(row=0, column=2, padx=(2, 6), pady=3, sticky="e")

        input_row = ctk.CTkFrame(qa_card, fg_color="transparent")
        input_row.pack(fill="x", padx=8, pady=3)
        input_row.grid_columnconfigure(0, weight=1)

        self.entry_query = ctk.CTkEntry(
            input_row,
            height=28,
            placeholder_text="对着麦克风说话，或输入问题回车发送（自动附带前5秒视频）...",
        )
        self.entry_query.grid(row=0, column=0, padx=(0, 6), sticky="ew")
        self.entry_query.bind("<Return>", lambda e: self._on_send_text_click())

        self.btn_send = ctk.CTkButton(input_row, text="发送提问", width=76, height=28, command=self._on_send_text_click)
        self.btn_send.grid(row=0, column=1)

        # 大模型对话快捷按钮 + 零延迟舵机动作秒测按钮
        quick_row = ctk.CTkFrame(qa_card, fg_color="transparent")
        quick_row.pack(fill="x", padx=8, pady=(2, 6))
        quick_row.grid_columnconfigure((0, 1, 2, 3, 4), weight=1)

        ctk.CTkButton(
            quick_row, text="😄 问答【笑】", height=24, fg_color="#2E7D32",
            command=lambda: self._trigger_manual_query("我们嵌入式大赛具身智能调试成功啦，好开心！")
        ).grid(row=0, column=0, padx=2, sticky="ew")
        ctk.CTkButton(
            quick_row, text="😢 问答【难过】", height=24, fg_color="#1565C0",
            command=lambda: self._trigger_manual_query("今天训练模型出了好几个报错，心里好难过啊。")
        ).grid(row=0, column=1, padx=2, sticky="ew")
        ctk.CTkButton(
            quick_row, text="🎥 问前5秒画面", height=24, fg_color="#6A1B9A",
            command=lambda: self._trigger_manual_query("请仔细看刚才这五秒视频，画面里有什么？我在做什么？")
        ).grid(row=0, column=2, padx=2, sticky="ew")
        ctk.CTkButton(
            quick_row, text="⚡ 秒测【笑】动作", height=24, fg_color="#00838F",
            command=lambda: self._trigger_instant_demo("smile")
        ).grid(row=0, column=3, padx=2, sticky="ew")
        ctk.CTkButton(
            quick_row, text="⚡ 秒测【难过】动作", height=24, fg_color="#37474F",
            command=lambda: self._trigger_instant_demo("sad")
        ).grid(row=0, column=4, padx=2, sticky="ew")
        ctk.CTkButton(quick_row, text="右眼 wink", height=24, fg_color="#00838F",
                     command=lambda: self._trigger_instant_demo("wink")).grid(row=1, column=0, columnspan=2, padx=2, pady=3, sticky="ew")
        ctk.CTkButton(quick_row, text="回自然", height=24, fg_color="#37474F",
                     command=lambda: self._trigger_instant_demo("neutral")).grid(row=1, column=2, padx=2, pady=3, sticky="ew")
        ctk.CTkButton(quick_row, text="wink 方向确认", height=24, fg_color="#37474F",
                     command=self._open_wink_setup).grid(row=1, column=3, columnspan=2, padx=2, pady=3, sticky="ew")
        ctk.CTkButton(quick_row,text="动作库 / 执行许可",height=25,fg_color="#6A1B9A",
                     command=self._open_action_library).grid(row=2,column=0,columnspan=2,padx=2,pady=3,sticky="ew")
        for col,(title,prompt) in enumerate((("说：抬头","请你抬起头"),("说：抬眼","请你抬一下眼"),("说：摇头","请你摇摇头")),2):
            ctk.CTkButton(quick_row,text=title,height=25,fg_color="#37474F",
                         command=lambda text=prompt:self._trigger_manual_query(text)).grid(row=2,column=col,padx=2,pady=3,sticky="ew")

        # ---- 中栏卡片 2：表情-控制转换核心状态与四条实时包络进度条 ----
        conv_card = ctk.CTkFrame(mid_panel, corner_radius=8, fg_color="#1B2430")
        conv_card.grid(row=1, column=0, padx=8, pady=4, sticky="ew")

        conv_top = ctk.CTkFrame(conv_card, fg_color="transparent")
        conv_top.pack(fill="x", padx=8, pady=(6, 2))

        self.lbl_expr_badge = ctk.CTkLabel(
            conv_top,
            text="当前表情: 😐【无】 (neutral)",
            font=ctk.CTkFont(size=13, weight="bold"),
            text_color="#FFFFFF",
            fg_color="#37474F",
            corner_radius=6,
            padx=10,
            pady=3,
        )
        self.lbl_expr_badge.pack(side="left", padx=(0, 6))

        self.lbl_active_char = ctk.CTkLabel(
            conv_top,
            text="当前字: 「-」 | 均幅: 0.0 | 开度: 0.00",
            font=ctk.CTkFont(family="Consolas", size=12, weight="bold"),
            text_color="#FFF59D",
            fg_color="#263238",
            corner_radius=6,
            padx=10,
            pady=3,
        )
        self.lbl_active_char.pack(side="left", fill="x", expand=True)

        bars_frame = ctk.CTkFrame(conv_card, fg_color="transparent")
        bars_frame.pack(fill="x", padx=8, pady=(2, 6))
        bars_frame.grid_columnconfigure(1, weight=1)

        meter_defs = [
            ("情绪包络 (Ease-in/out):", "bar_emo_env", "lbl_emo_env", "#FFB74D"),
            ("音节嘴形 (CH10~13 唇):", "bar_lip_energy", "lbl_lip_energy", "#4FC3F7"),
            ("重音抬眉 (CH2~5 眉):", "bar_accent", "lbl_accent", "#AED581"),
            ("自然眨眼 (CH6~9 睑):", "bar_blink", "lbl_blink", "#CE93D8"),
        ]
        for r_idx, (title_txt, bar_attr, lbl_attr, color_hex) in enumerate(meter_defs):
            ctk.CTkLabel(bars_frame, text=title_txt, font=ctk.CTkFont(size=11)).grid(
                row=r_idx, column=0, sticky="w", padx=(2, 6), pady=2
            )
            p_bar = ctk.CTkProgressBar(bars_frame, progress_color=color_hex, height=10)
            p_bar.set(0.0)
            p_bar.grid(row=r_idx, column=1, sticky="ew", padx=4, pady=2)
            setattr(self, bar_attr, p_bar)

            v_lbl = ctk.CTkLabel(
                bars_frame,
                text="0.00",
                font=ctk.CTkFont(family="Consolas", size=11),
                width=90,
                anchor="e",
            )
            v_lbl.grid(row=r_idx, column=2, sticky="e", padx=4, pady=2)
            setattr(self, lbl_attr, v_lbl)

        # ---- 中栏卡片 3：逐字平均振幅时间轴 -> CH10~13 四路唇部转换明细表 ----
        table_card = ctk.CTkFrame(mid_panel, corner_radius=8, fg_color="#181E29")
        table_card.grid(row=2, column=0, padx=8, pady=4, sticky="nsew")
        table_card.grid_rowconfigure(1, weight=1)
        table_card.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(
            table_card,
            text="3. 逐字平均振幅时间轴 (char_amplitudes) -> 四路唇部 (CH10~13) 转换明细",
            font=ctk.CTkFont(size=12, weight="bold"),
            text_color="#FFD54F",
        ).grid(row=0, column=0, sticky="w", padx=8, pady=(6, 2))

        self.txt_char_table = ctk.CTkTextbox(
            table_card,
            font=ctk.CTkFont(family="Consolas", size=11),
            fg_color="#0F131A",
            text_color="#E0E0E0",
        )
        self.txt_char_table.grid(row=1, column=0, sticky="nsew", padx=8, pady=(0, 6))

        # ---- 中栏卡片 4：全链路系统事件日志 ----
        log_card = ctk.CTkFrame(mid_panel, corner_radius=8, fg_color="#141820")
        log_card.grid(row=3, column=0, padx=8, pady=(4, 8), sticky="nsew")
        log_card.grid_rowconfigure(1, weight=1)
        log_card.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(
            log_card,
            text="4. 全链路运行日志 (同步持久化 build/expression_control_latest.json):",
            font=ctk.CTkFont(size=11, weight="bold"),
            text_color="#90CAF9",
        ).grid(row=0, column=0, padx=8, pady=(4, 2), sticky="w")

        self.txt_log = ctk.CTkTextbox(
            log_card,
            font=ctk.CTkFont(family="Consolas", size=11),
            activate_scrollbars=True,
        )
        self.txt_log.grid(row=1, column=0, padx=8, pady=(0, 6), sticky="nsew")

        # ==================== 右栏：NH22 v4 全部 22 路舵机实时脉宽矩阵与控制参数 ====================
        right_panel = ctk.CTkFrame(self, corner_radius=10)
        right_panel.grid(row=1, column=2, padx=(5, 10), pady=6, sticky="nsew")
        right_panel.grid_rowconfigure(1, weight=1)
        right_panel.grid_columnconfigure(0, weight=1)

        # 右栏顶部：参数配置与眨眼控制
        r_top = ctk.CTkFrame(right_panel, fg_color="transparent")
        r_top.grid(row=0, column=0, sticky="ew", padx=8, pady=(8, 4))

        ctk.CTkLabel(
            r_top,
            text="5. NH22 22路舵机实时脉宽",
            font=ctk.CTkFont(size=13, weight="bold"),
            text_color="#A5D6A7",
        ).pack(side="left", padx=(2, 6))

        ctk.CTkButton(
            r_top,
            text="👀 单次眨眼",
            fg_color="#6A1B9A",
            hover_color="#4A148C",
            width=82,
            height=24,
            command=lambda: self.nh22_runtime.trigger_blink(),
        ).pack(side="right", padx=3)

        self.seg_neck = ctk.CTkSegmentedButton(
            r_top,
            values=["normal", "faster"],
            command=self._on_neck_speed_change,
            height=24,
        )
        self.seg_neck.set("faster")
        self.seg_neck.pack(side="right", padx=3)

        self.seg_style = ctk.CTkSegmentedButton(
            r_top,
            values=["soft", "lively", "active"],
            command=self._on_style_change,
            height=24,
        )
        self.seg_style.set("active")
        self.seg_style.pack(side="right", padx=3)

        # 22 路通道矩阵滚动框
        ch_scroll = ctk.CTkScrollableFrame(right_panel, fg_color="#131B24", corner_radius=8)
        ch_scroll.grid(row=1, column=0, sticky="nsew", padx=8, pady=4)
        ch_scroll.grid_columnconfigure(2, weight=1)

        group_colors = {
            "eye": "#29B6F6",
            "brow": "#FFA726",
            "eyelid": "#AB47BC",
            "lip": "#EF5350",
            "cheek": "#78909C",
            "neck": "#66BB6A",
            "jaw": "#8D6E63",
        }

        for row_idx in range(NH22_CHANNEL_COUNT):
            spec = self.nh22_runtime.converter.registry.channels[row_idx]
            g_color = group_colors.get(spec.group, "#90A4AE")
            status_tag = "启用" if spec.enabled else ("仅探查" if spec.probe_only else "待确认")

            lbl_info = ctk.CTkLabel(
                ch_scroll,
                text=f"CH{spec.channel:02d}(P{spec.j10_pin:02d}) {spec.label}",
                font=ctk.CTkFont(family="Consolas", size=11, weight="bold"),
                text_color=g_color,
                width=150,
                anchor="w",
            )
            lbl_info.grid(row=row_idx, column=0, sticky="w", padx=(4, 2), pady=2)

            act_str = f"动:{spec.action_us}" if spec.action_us is not None else "追踪"
            lbl_meta = ctk.CTkLabel(
                ch_scroll,
                text=f"[{spec.min_us}..{spec.max_us} 中:{spec.neutral_us} {act_str}|{status_tag}]",
                font=ctk.CTkFont(family="Consolas", size=10),
                text_color="#90A4AE",
                width=235,
                anchor="w",
            )
            lbl_meta.grid(row=row_idx, column=1, sticky="w", padx=2, pady=2)

            bar = ctk.CTkProgressBar(ch_scroll, progress_color=g_color, height=10)
            bar.set((spec.neutral_us - 1000.0) / 1000.0)
            bar.grid(row=row_idx, column=2, sticky="ew", padx=4, pady=2)
            self.channel_bars[row_idx] = bar

            lbl_val = ctk.CTkLabel(
                ch_scroll,
                text=f"{spec.neutral_us:4d} us",
                font=ctk.CTkFont(family="Consolas", size=11, weight="bold"),
                width=64,
                anchor="e",
            )
            lbl_val.grid(row=row_idx, column=3, sticky="e", padx=(2, 6), pady=2)
            self.channel_val_labels[row_idx] = lbl_val

        # 右栏底部：62B 硬件帧 Hex 预览
        pkt_box = ctk.CTkFrame(right_panel, corner_radius=8, fg_color="#1B2430")
        pkt_box.grid(row=2, column=0, sticky="ew", padx=8, pady=(4, 8))

        self.lbl_nh_hex = ctk.CTkLabel(
            pkt_box,
            text="NH22 v3 Frame (62B): 等待中...",
            font=ctk.CTkFont(family="Consolas", size=10),
            text_color="#B0BEC5",
            anchor="w",
            justify="left",
        )
        self.lbl_nh_hex.pack(fill="x", padx=8, pady=5)
