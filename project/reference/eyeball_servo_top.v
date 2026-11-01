`timescale 1ns / 1ps

module eyeball_servo_top #(
    parameter CLK_FREQ      = 50_000_000, // AX7020 PL端系统时钟 50MHz
    parameter PWM_PERIOD    = 1_000_000,  // 20ms 周期 (50Hz)
    
    // 角度限位参数 (默认限制在 45° ~ 135° 防止眼球连杆机械干涉，可按需放宽至 25000~125000)
    parameter PULSE_LEFT    = 50_000,     // 左视极限: 1.0ms (约45度)
    parameter PULSE_CENTER  = 75_000,     // 居中正视: 1.5ms (90度)
    parameter PULSE_RIGHT   = 100_000,    // 右视极限: 2.0ms (约135度)
    
    // 运动速度与停顿参数
    parameter STEP_SIZE     = 500,        // 每次20ms周期脉宽变化量 (500 * 20ns = 10us, 约0.9度/周期)
    parameter DWELL_PERIODS = 20          // 左右极限处停顿周期数 (20 * 20ms = 400ms 凝视效果)
)(
    input  wire sys_clk,      // 50MHz 系统时钟 (U18)
    input  wire sys_rst_n,    // 复位按键，低电平有效 (N15 - KEY1)
    input  wire key_enable_n, // 启停/居中切换按键，低电平有效 (N16 - KEY2)
    output reg  servo_pwm,    // MG90S PWM 信号输出
    output wire [1:0] led     // 状态指示灯: led[0]方向指示, led[1]运行状态
);

    // =========================================================================
    // 1. 按键消抖与启停状态切换 (KEY2 控制眼球"自动扫视"与"回中静止"切换)
    // =========================================================================
    reg [19:0] debounce_cnt;
    reg        key_reg0, key_reg1, key_stable;
    reg        key_stable_d;
    reg        move_enable; // 1: 左右扫视模式, 0: 居中注视模式

    always @(posedge sys_clk or negedge sys_rst_n) begin
        if (!sys_rst_n) begin
            key_reg0     <= 1'b1;
            key_reg1     <= 1'b1;
            key_stable   <= 1'b1;
            key_stable_d <= 1'b1;
            debounce_cnt <= 20'd0;
            move_enable  <= 1'b1; // 上电默认开启左右移动
        end else begin
            key_reg0 <= key_enable_n;
            key_reg1 <= key_reg0;
            
            if (key_reg1 != key_stable) begin
                if (debounce_cnt < 20'd999_999) // 20ms 消抖
                    debounce_cnt <= debounce_cnt + 1'b1;
                else begin
                    key_stable   <= key_reg1;
                    debounce_cnt <= 20'd0;
                end
            end else begin
                debounce_cnt <= 20'd0;
            end
            
            key_stable_d <= key_stable;
            // 检测按键下降沿切换模式
            if (key_stable_d && !key_stable) begin
                move_enable <= ~move_enable;
            end
        end
    end

    // =========================================================================
    // 2. 20ms PWM 周期基准计数器
    // =========================================================================
    reg [19:0] period_cnt;
    wire       period_tick;

    assign period_tick = (period_cnt == PWM_PERIOD - 1);

    always @(posedge sys_clk or negedge sys_rst_n) begin
        if (!sys_rst_n) begin
            period_cnt <= 20'd0;
        end else if (period_tick) begin
            period_cnt <= 20'd0;
        end else begin
            period_cnt <= period_cnt + 1'b1;
        end
    end

    // =========================================================================
    // 3. 眼球左右运动轨迹控制状态机 (每个 PWM 周期更新一次脉宽，防止毛刺)
    // =========================================================================
    localparam S_MOVE_RIGHT = 2'd0;
    localparam S_DWELL_R    = 2'd1;
    localparam S_MOVE_LEFT  = 2'd2;
    localparam S_DWELL_L    = 2'd3;

    reg [1:0]  state;
    reg [19:0] pulse_width;
    reg [7:0]  dwell_cnt;

    always @(posedge sys_clk or negedge sys_rst_n) begin
        if (!sys_rst_n) begin
            state       <= S_MOVE_RIGHT;
            pulse_width <= PULSE_CENTER; // 复位时眼球回到正中 90°
            dwell_cnt   <= 8'd0;
        end else if (period_tick) begin
            if (!move_enable) begin
                // 暂停模式下平滑回归正中 (90°)
                if (pulse_width < PULSE_CENTER) begin
                    pulse_width <= (pulse_width + STEP_SIZE > PULSE_CENTER) ? PULSE_CENTER : (pulse_width + STEP_SIZE);
                end else if (pulse_width > PULSE_CENTER) begin
                    pulse_width <= (pulse_width - STEP_SIZE < PULSE_CENTER) ? PULSE_CENTER : (pulse_width - STEP_SIZE);
                end
            end else begin
                case (state)
                    S_MOVE_RIGHT: begin
                        if (pulse_width + STEP_SIZE >= PULSE_RIGHT) begin
                            pulse_width <= PULSE_RIGHT;
                            dwell_cnt   <= 8'd0;
                            state       <= S_DWELL_R;
                        end else begin
                            pulse_width <= pulse_width + STEP_SIZE;
                        end
                    end

                    S_DWELL_R: begin
                        if (dwell_cnt >= DWELL_PERIODS - 1) begin
                            dwell_cnt <= 8'd0;
                            state     <= S_MOVE_LEFT;
                        end else begin
                            dwell_cnt <= dwell_cnt + 1'b1;
                        end
                    end

                    S_MOVE_LEFT: begin
                        if (pulse_width - STEP_SIZE <= PULSE_LEFT) begin
                            pulse_width <= PULSE_LEFT;
                            dwell_cnt   <= 8'd0;
                            state       <= S_DWELL_L;
                        end else begin
                            pulse_width <= pulse_width - STEP_SIZE;
                        end
                    end

                    S_DWELL_L: begin
                        if (dwell_cnt >= DWELL_PERIODS - 1) begin
                            dwell_cnt <= 8'd0;
                            state     <= S_MOVE_RIGHT;
                        end else begin
                            dwell_cnt <= dwell_cnt + 1'b1;
                        end
                    end

                    default: state <= S_MOVE_RIGHT;
                endcase
            end
        end
    end

    // =========================================================================
    // 4. PWM 比较输出级 (寄存器打拍输出消除组合逻辑毛刺)
    // =========================================================================
    always @(posedge sys_clk or negedge sys_rst_n) begin
        if (!sys_rst_n) begin
            servo_pwm <= 1'b0;
        end else begin
            servo_pwm <= (period_cnt < pulse_width) ? 1'b1 : 1'b0;
        end
    end

    // LED 状态指示 (AX7020 PL LED 高电平点亮)
    assign led[0] = (state == S_MOVE_RIGHT || state == S_DWELL_R); // 朝右时亮
    assign led[1] = move_enable;                                   // 运动激活时亮

endmodule