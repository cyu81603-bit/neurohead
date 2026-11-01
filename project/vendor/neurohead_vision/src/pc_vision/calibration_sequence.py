"""Bounded, simulation-only repeat demo and source-grounded result export."""
import json
from pathlib import Path
import time


class CalibrationSequence:
    def __init__(self, controller):
        self.controller = controller
        self.active = False
        self.status = 'not_started'
        self.results = []
        self.reason = ''
        self.steps = []

    def start_demo(self, joint):
        c = self.controller
        if not c.sim:
            raise ValueError('三组自动往复当前仅用于本机模拟，不驱动实体机构')
        if self.active or c.phase != 'idle':
            raise ValueError('请等待当前动作结束')
        self.steps = [dict(group=group, joint=joint, target_us=target)
                      for group in range(1,4) for target in (1475,1525)]
        for step in self.steps:
            reason = c.permission_reason(joint,step['target_us'])
            if reason:
                raise ValueError(reason)
        self.started = time.monotonic()
        self.command_start = c.command_frames_sent
        self.results, self.reason = [], ''
        self.index = 0
        self.status, self.active = 'running', True
        try:
            self._start_step(prepare=2)
        except (ValueError,OSError) as exc:
            self.cancel(str(exc))
            raise

    def _start_step(self, prepare):
        c = self.controller
        step = self.steps[self.index]
        self.event_start = len(c.events)
        self.step_command_start = c.command_frames_sent
        self.reached = False
        self.other_neutral = True
        c.start(step['joint'],step['target_us'],hold=2,prepare=prepare)

    def cancel(self, reason='操作者停止自动序列'):
        if self.active:
            self.active = False
            self.status, self.reason = 'aborted', reason
            self.finished = time.monotonic()
            self.controller.stop(reason)

    def tick(self):
        if not self.active:
            return
        c = self.controller
        step = self.steps[self.index]
        axis = c.profiles[step['joint']]['channel']
        other = 'pitch' if axis=='yaw' else 'yaw'
        if c.state and time.monotonic()-c.last_rx<.4:
            self.reached = self.reached or c.state['output_'+axis+'_us']==step['target_us']
            self.other_neutral = self.other_neutral and c.state['output_'+other+'_us']==1500
        events = c.events[self.event_start:]
        bad_stop = next((e for e in events if e['event']=='commands_stopped' and e['reason']!='定时动作结束'),None)
        if bad_stop:
            self.cancel(bad_stop['reason'])
            return
        returned = next((e for e in reversed(events) if e['event']=='return_readback'),None)
        if c.phase!='idle' or returned is None:
            return
        sent = c.command_frames_sent-self.step_command_start
        passed = bool(returned['confirmed'] and self.reached and self.other_neutral and sent>0)
        self.results.append(dict(step, command_frames_sent=sent, target_setting_reached=self.reached,
                                 other_channel_neutral=self.other_neutral,
                                 return_readback_confirmed=returned['confirmed'], digital_passed=passed))
        if not passed:
            self.cancel('目标回读、另一通道中位或看门狗返回检查未通过')
            return
        self.index += 1
        if self.index==len(self.steps):
            self.active = False
            self.status = 'completed'
            self.finished = time.monotonic()
            return
        try:
            self._start_step(prepare=0)
        except (ValueError,OSError) as exc:
            self.cancel(str(exc))

    def summary(self):
        c = self.controller
        return dict(schema_version=1, mode=c.mode, status=self.status,
                    reason=self.reason, planned_groups=3, planned_steps=len(self.steps),
                    completed_steps=len(self.results), results=self.results,
                    command_frames_sent=c.command_frames_sent-getattr(self,'command_start',c.command_frames_sent),
                    elapsed_s=max(0,getattr(self,'finished',time.monotonic())-getattr(self,'started',time.monotonic())),
                    evidence='simulation_only', physical_motion_tested=False,
                    final_state=c.state,
                    all_digital_checks_passed=self.status=='completed' and len(self.results)==6 and all(r['digital_passed'] for r in self.results),
                    boundary='Functional loopback model and host state machine only; not RTL timing, board pin measurement, shaft-angle accuracy or mechanical clearance.')

    def export(self, directory, stem):
        if self.status not in ('completed','aborted'):
            raise ValueError('序列尚未结束，不能导出完成报告')
        if not stem or any(ch not in 'abcdefghijklmnopqrstuvwxyz0123456789_-' for ch in stem):
            raise ValueError('Invalid report stem')
        directory=Path(directory)
        directory.mkdir(parents=True,exist_ok=True)
        data=self.summary()
        json_path=directory/(stem+'.json')
        md_path=directory/(stem+'.md')
        json_path.write_text(json.dumps(data,indent=2,ensure_ascii=False),encoding='utf-8')
        lines=['# 模拟往复验证报告','',
               '**证据范围：仅本机UDP功能模型。没有驱动或验证真实机器人。**','',
               f"- 状态：{data['status']}",
               f"- 数字检查全部通过：{data['all_digital_checks_passed']}",
               f"- 已完成步骤：{data['completed_steps']} / {data['planned_steps']}",
               f"- 发送命令帧：{data['command_frames_sent']}",
               f"- 主机过程耗时：{data['elapsed_s']:.3f} s（不是实时性能指标）",'']
        if data['reason']:
            lines += ['中断原因：'+data['reason'],'']
        lines += ['| 组 | 关节 | 目标 μs | 目标回读 | 另一通道1500 | 返回回读 |',
                  '|---|---|---:|---|---|---|']
        for r in data['results']:
            lines.append(f"| {r['group']} | {r['joint']} | {r['target_us']} | {r['target_setting_reached']} | {r['other_channel_neutral']} | {r['return_readback_confirmed']} |")
        lines += ['', '尚未验证：实体机构行程、卡滞解除、角度、负载电流、实际PWM抖动、硬件延迟。',
                  '停止序列只停止本窗口发送，不切断电源。模拟结果不解锁任何真实关节。','']
        md_path.write_text('\n'.join(lines),encoding='utf-8')
        return json_path,md_path
