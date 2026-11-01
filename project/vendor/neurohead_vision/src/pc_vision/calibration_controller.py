"""Local calibration transport. Read-only by default; simulation is not board proof."""
import json
from pathlib import Path
import socket
import time

from monitor_protocol import make_query, parse_telemetry
from send_neurohead_udp import make_frame
from simulated_board import SimulatedBoard
from board_network import bind_board_socket

ROOT = Path(__file__).resolve().parents[2]


def load_profiles(path=ROOT/'data/calibration_profiles.json'):
    data = json.loads(Path(path).read_text(encoding='utf-8'))
    joints = data['joints']
    for key, p in joints.items():
        if p['channel'] not in ('yaw', 'pitch'):
            raise ValueError(f'{key}: only the two implemented channels are supported')
        if any(type(p[k]) is not int for k in ('min_us', 'center_us', 'max_us')):
            raise ValueError('Integer microseconds required')
        if not 600 <= p['min_us'] <= p['center_us'] <= p['max_us'] <= 2400:
            raise ValueError('Invalid pulse envelope')
        if p['center_us'] != 1500 or not p['min_us'] <= 1500 <= p['max_us']:
            raise ValueError('This hardware watchdog returns to 1500 us')
        if type(p['verified']) is not bool:
            raise ValueError('verified must be boolean')
    return joints


class CalibrationController:
    def __init__(self, mode='sim', profiles=None, enable_board_motion=False,
                 fault_dir=ROOT/'data/joint_setups'):
        if mode not in ('sim', 'board'):
            raise ValueError('Unknown mode')
        self.mode = mode
        self.profiles = profiles if profiles is not None else load_profiles()
        self.enable_board_motion = enable_board_motion
        self.fault_dir = Path(fault_dir)
        self.sim = SimulatedBoard() if mode == 'sim' else None
        self.peer = self.sim.start() if self.sim else ('192.168.10.20', 5005)
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.interface_index = None
        try:
            if self.sim:
                self.sock.bind(('127.0.0.1', 0))
            else:
                self.interface_index = bind_board_socket(self.sock)
        except Exception:
            self.sock.close()
            raise
        self.sock.setblocking(False)
        self.state = None
        self.last_rx = self.last_query = self.last_command = 0.0
        self.token = int(time.perf_counter()*1000) & 0xffffffff
        self.pending = {}
        self.events, self.samples = [], []
        self.phase = 'idle'
        self.action = None
        self.command_frames_sent = 0
        self.message = '等待兼容遥测'

    def envelope(self, joint):
        if self.sim:
            return 1450, 1550  # simulation-only example, never written to board profiles
        p = self.profiles[joint]
        return p['min_us'], p['max_us']

    def fault_reason(self):
        if self.sim:
            return ''
        try:
            if not self.fault_dir.is_dir():
                return '关节故障目录缺失，保持只读'
            files = list(self.fault_dir.glob('*.json'))
            if not files:
                return '没有关节状态记录，保持只读'
            for path in files:
                p = json.loads(path.read_text(encoding='utf-8'))
                if not isinstance(p, dict) or type(p.get('motion_inhibited', False)) is not bool:
                    return f'{path.stem}: 故障状态格式错误，保持只读'
                if p.get('motion_inhibited', False):
                    return f'{path.stem}: 机械故障禁用尚未解除'
        except (OSError, ValueError, AttributeError):
            return '无法读取关节故障状态，保持只读'
        return ''

    def permission_reason(self, joint, target):
        if joint not in self.profiles or type(target) is not int:
            return '未知关节或非整数微秒值'
        if not self.sim:
            reason = self.fault_reason()
            if reason:
                return reason
            if not self.enable_board_motion:
                return '真实板卡当前为只读模式'
            if self.profiles[joint]['verified'] is not True:
                return '该关节尚无已验证的安全范围'
        low, high = self.envelope(joint)
        if not low <= target <= high:
            return f'超出本会话范围 {low}..{high} us'
        if self.state is None or time.monotonic()-self.last_rx > .4:
            return '无新鲜遥测，禁止动作'
        return ''

    def start(self, joint, target, hold=5, prepare=2):
        if self.phase != 'idle':
            raise ValueError('当前动作未结束；可按停止发送')
        if hold not in (2, 5) or prepare not in (0, 2):
            raise ValueError('Invalid bounded timing')
        reason = self.permission_reason(joint, target)
        if reason:
            raise ValueError(reason)
        if not self.state['status'] & 1 or any(self.state[k] != 1500 for k in ('output_yaw_us', 'output_pitch_us')):
            raise ValueError('等待看门狗状态及1500 us输出设置后再开始')
        now = time.monotonic()
        s = self.state
        self.action = dict(joint=joint, target=target, hold=hold, prepare_until=now+prepare,
                           end=now+prepare+hold, sequence=(s['sequence']+1)&0xffff if s['have_sequence'] else 0,
                           accepted=s['accepted'], invalid=s['invalid'], stale=s['stale'], sent=0)
        self.phase = 'prepare'
        self.events.append(dict(event='start', monotonic_s=now, joint=joint, target_us=target, hold_s=hold))

    def stop(self, reason='操作者停止发送'):
        if self.phase in ('prepare', 'hold'):
            self.phase = 'return'
            self.return_deadline = time.monotonic()+1.5
            self.events.append(dict(event='commands_stopped', reason=reason, monotonic_s=time.monotonic()))
        self.message = reason+'；软件不切断舵机电源'

    def _send(self, packet, token, kind, **expected):
        now = time.monotonic()
        self.sock.sendto(packet, self.peer)
        self.pending[token] = dict(sent=now, kind=kind, **expected)

    def _token(self):
        self.token = (self.token+1)&0xffffffff
        return self.token

    def tick(self):
        now = time.monotonic()
        # Fault/permission checks run before every possible command, not only at arm time.
        if self.phase in ('prepare', 'hold'):
            reason = self.permission_reason(self.action['joint'], self.action['target'])
            if reason:
                self.stop(reason)
        for _ in range(64):
            try:
                raw, addr = self.sock.recvfrom(2048)
            except BlockingIOError:
                break
            if addr != self.peer:
                continue
            try:
                s = parse_telemetry(raw)
            except ValueError:
                continue
            pending = self.pending.get(s['echo_timestamp_ms'])
            if not pending or s['simulated'] != bool(self.sim) or s['query'] != (pending['kind'] == 'query'):
                continue
            self.pending.pop(s['echo_timestamp_ms'])
            if self.state is None:
                self.message = '遥测已连接；尚未发送动作'
            self.state, self.last_rx = s, now
            self.samples.append(dict(s, phase=self.phase, monotonic_s=now,
                                     host_poll_rtt_ms=(now-pending['sent'])*1000))
            if pending['kind'] == 'command':
                if s['sequence'] != pending['sequence'] or s['accepted'] != pending['accepted']:
                    self.stop('命令序号/计数不匹配')
            if self.phase in ('prepare', 'hold'):
                if s['invalid'] != self.action['invalid'] or s['stale'] != self.action['stale']:
                    self.stop('出现拒绝计数或其他发送端')
                elif ((s['accepted']-self.action['accepted'])&0xffffffff) > self.action['sent']:
                    self.stop('板卡重启或其他发送端改变了计数')
        expired = [k for k,v in self.pending.items() if now-v['sent'] > .25]
        for token in expired:
            if self.pending.pop(token)['kind'] == 'command':
                self.stop('命令响应超时')
        if now-self.last_query >= .1:
            token = self._token()
            self._send(make_query(token&0xffff, token), token, 'query')
            self.last_query = now
        if self.phase == 'prepare' and now >= self.action['prepare_until']:
            self.phase = 'hold'
        if self.phase == 'hold':
            a = self.action
            if now >= a['end']:
                self.stop('定时动作结束')
            elif now-self.last_command >= .05 and not any(v['kind']=='command' for v in self.pending.values()):
                # Repeat the gate after receiving packets and immediately before send.
                reason = self.permission_reason(a['joint'], a['target'])
                if reason:
                    self.stop(reason)
                else:
                    values = [1500, 1500]
                    values[0 if self.profiles[a['joint']]['channel']=='yaw' else 1] = a['target']
                    token = self._token()
                    a['sent'] += 1
                    self._send(make_frame(a['sequence'], *values, token), token, 'command',
                               sequence=a['sequence'], accepted=(a['accepted']+a['sent'])&0xffffffff)
                    a['sequence'] = (a['sequence']+1)&0xffff
                    self.last_command = now
                    self.command_frames_sent += 1
        if self.phase == 'return':
            fresh = self.state is not None and now-self.last_rx < .4
            returned = fresh and self.state['status']&3 == 3 and all(self.state[k]==1500 for k in ('output_yaw_us','output_pitch_us'))
            if returned or now >= self.return_deadline:
                self.events.append(dict(event='return_readback', confirmed=bool(returned), monotonic_s=now))
                self.message = '回读已到1500 us；机械动作仍需现场确认' if returned else '回中回读未确认；检查外部电源和现场状态'
                self.phase = 'idle'

    def close(self):
        self.stop('关闭面板')
        self.sock.close()
        if self.sim:
            self.sim.close()
