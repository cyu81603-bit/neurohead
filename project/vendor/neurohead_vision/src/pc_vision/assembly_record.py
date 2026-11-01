"""Operator assembly notes with query-only evidence; never changes motion gates."""
from datetime import datetime
import hashlib
import json
import time


CHOICES = {
    'power': ('未确认', '外部电源关闭', '外部电源开启'),
    'signal': ('未确认', '信号线已拔开', '信号线已接回'),
    'linkage': ('未确认', '驱动接头脱开', '连杆已装回'),
    'binding': ('未确认', '卡滞尚未处理', '操作者报告已处理'),
    'neutral': ('未确认', '沿用1500 μs定位后舵盘位置且双眼朝前', '装回时未核对1500 μs位置'),
}
LABELS = dict(power='外部供电', signal='信号线', linkage='机械连接',
              binding='卡滞处理', neutral='装配零位')


def capture(client, joint, observations, note=''):
    if set(observations) != set(CHOICES):
        raise ValueError('装配记录字段不完整')
    if any(value not in CHOICES[key] for key, value in observations.items()):
        raise ValueError('未知装配选项')
    profile = dict(client.profiles[joint])
    path = client.fault_dir / (joint + '.json')
    fault, fault_hash, error = None, None, None
    try:
        raw = path.read_bytes()
        fault_hash = hashlib.sha256(raw).hexdigest()
        fault = json.loads(raw)
        if not isinstance(fault, dict):
            raise ValueError('故障状态不是对象')
    except (OSError, ValueError) as exc:
        fault, error = None, str(exc)
    age = max(0, time.monotonic() - client.last_rx) if client.state is not None else None
    fresh = age is not None and age < .4
    return dict(
        schema_version=1, recorded_at=datetime.now().astimezone().isoformat(),
        joint=joint, label=profile['label'], mode=client.mode,
        operator_observations=dict(observations), operator_note=note,
        observation_authority='operator_report_not_independent_verification',
        profile_snapshot=profile, fault_snapshot=fault, fault_sha256=fault_hash,
        fault_read_error=error, motion_gate_reason=client.permission_reason(joint, 1500),
        telemetry_fresh=fresh, telemetry_age_s=age,
        telemetry=dict(client.state) if fresh else None,
        telemetry_evidence='simulation_only' if client.sim else 'board_register_readback',
        interface_index=client.interface_index,
        session_command_frames_sent=client.command_frames_sent,
        range_verified=False, angles_measured=False, interlock_changed=False,
        next_step='核对机械零位与安装余量；现场记录不自动解除动作禁用。')


def save(client, joint, observations, note, run_dir):
    record = capture(client, joint, observations, note)
    stem = f'assembly_{datetime.now():%Y%m%d_%H%M%S_%f}_{joint}'
    json_path, md_path = run_dir / (stem + '.json'), run_dir / (stem + '.md')
    lines = [f"# {record['label']}：装配记录", '', f"时间：{record['recorded_at']}",
             f"模式：{record['mode']}；记录由操作者填写，未独立验证。", '']
    lines += [f'- {LABELS[key]}：{value}' for key, value in observations.items()]
    lines += ['', f'备注：{note or "未填写"}', '',
              f"动作限制：{record['motion_gate_reason'] or '本记录不提供运动授权'}",
              f"遥测新鲜：{record['telemetry_fresh']}；本窗口累计动作帧：{client.command_frames_sent}",
              '遥测为脉宽寄存器设置，不是实测舵机角度。',
              '记录不修改故障状态或运行范围；尚无实测机械行程。', '', record['next_step'], '']
    json_path.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding='utf-8')
    md_path.write_text('\n'.join(lines), encoding='utf-8')
    return json_path, md_path
