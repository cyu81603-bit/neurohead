#!/usr/bin/env python3
"""No-install Tk dashboard. Simulation by default, board mode queries only until armed."""
import argparse
from collections import deque
import csv
from datetime import datetime
import json
from pathlib import Path
import socket
import time
import tkinter as tk
from tkinter import ttk, messagebox

from monitor_protocol import make_query, parse_telemetry
from send_neurohead_udp import make_frame
from simulated_board import SimulatedBoard

ROOT = Path(__file__).resolve().parents[2]


def load_profile(path):
    profile = json.loads(Path(path).read_text(encoding='utf-8'))
    for axis in ('yaw', 'pitch'):
        p = profile[axis]
        for field in ('min_us', 'center_us', 'max_us'):
            if type(p[field]) is not int:
                raise ValueError(f'{axis}.{field}: integer microseconds required')
        if not 600 <= p['min_us'] <= p['center_us'] <= p['max_us'] <= 2400:
            raise ValueError(f'{axis}: invalid pulse limits')
        if not p['min_us'] <= 1500 <= p['max_us']:
            raise ValueError(f'{axis}: legacy PL watchdog returns to 1500 us; this must be mechanically safe')
        if type(p.get('verified')) is not bool:
            raise ValueError(f'{axis}: verified must be a boolean')
    return profile


class Dashboard:
    def __init__(self, root, args):
        self.root, self.args = root, args
        self.profile = load_profile(args.profile)
        self.sim = SimulatedBoard() if args.mode == 'sim' else None
        self.endpoint = self.sim.start() if self.sim else (socket.gethostbyname(args.host), args.port)
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.bind(('127.0.0.1' if self.sim else args.bind_ip, 0))
        self.sock.setblocking(False)
        self.armed = False
        self.sequence = self.query_sequence = 0
        self.synchronized = False
        self.last_rx = self.last_tx = self.last_query = 0.0
        self.last_good = None
        self.pending = {}
        self.points = deque(maxlen=300)
        self.rtts = deque(maxlen=500)
        self.start_time = time.monotonic()
        stamp = datetime.now().strftime('%Y%m%d_%H%M%S_%f')
        self.run_dir = ROOT / 'data' / 'dashboard_runs' / f'{stamp}_{args.mode}'
        self.run_dir.mkdir(parents=True, exist_ok=True)
        (self.run_dir/'manifest.json').write_text(json.dumps({
            'mode': args.mode, 'endpoint': self.endpoint, 'profile': self.profile,
            'started_local': datetime.now().isoformat(),
            'evidence': 'simulation_only' if self.sim else 'network_telemetry_not_angle_measurement',
            'rtt_definition': 'host sendto to telemetry receive; not one-way or camera-to-motion latency'
        }, indent=2, ensure_ascii=False), encoding='utf-8')
        self.log = (self.run_dir/'telemetry.csv').open('w', newline='', encoding='utf-8')
        self.columns = ['elapsed_s', 'mode', 'rtt_ms', 'sequence', 'status',
                        'target_yaw_us', 'target_pitch_us', 'output_yaw_us', 'output_pitch_us',
                        'accepted', 'invalid', 'stale', 'watchdog_events', 'simulated']
        self.writer = csv.DictWriter(self.log, fieldnames=self.columns, extrasaction='ignore')
        self.writer.writeheader()
        root.title('NeuroHead | SIMULATION' if self.sim else 'NeuroHead | BOARD MONITOR')
        root.geometry('960x660')
        body = ttk.Frame(root, padding=16)
        body.pack(fill='both', expand=True)
        ttk.Label(body, text='NeuroHead - SIMULATION / no physical hardware' if self.sim else
                  'NeuroHead - AX7020 / read-only until armed', font=('', 17, 'bold')).pack(anchor='w')
        ttk.Label(body, text=f'UDP {self.endpoint[0]}:{self.endpoint[1]} | 20 Hz command / 10 Hz query').pack(anchor='w', pady=6)
        self.status_text = tk.StringVar(value='Waiting for telemetry...')
        ttk.Label(body, textvariable=self.status_text).pack(anchor='w', pady=4)
        self.values_text = tk.StringVar(value='PL PWM settings are NOT measured shaft angles.')
        ttk.Label(body, textvariable=self.values_text, font=('Consolas', 11)).pack(anchor='w', pady=4)
        self.counters_text = tk.StringVar()
        ttk.Label(body, textvariable=self.counters_text).pack(anchor='w')
        self.sliders = []
        for axis in ('yaw', 'pitch'):
            p = self.profile[axis]
            row = ttk.Frame(body)
            row.pack(fill='x', pady=6)
            ttk.Label(row, text=f"{axis} / {p['joint']} (us)", width=30).pack(side='left')
            var = tk.IntVar(value=p['center_us'])
            tk.Scale(row, from_=p['min_us'], to=p['max_us'], variable=var,
                     resolution=1, orient='horizontal', length=510).pack(side='left')
            self.sliders.append(var)
        controls = ttk.Frame(body)
        controls.pack(fill='x', pady=8)
        ttk.Button(controls, text='Arm commands', command=self.arm).pack(side='left', padx=4)
        ttk.Button(controls, text='Stop commands (watchdog test)', command=self.stop).pack(side='left', padx=4)
        ttk.Button(controls, text='Set calibrated centre', command=self.center).pack(side='left', padx=4)
        ttk.Label(body, text='Stop ends commands; watchdog ramps to 1500 us. It does NOT cut servo power.').pack(anchor='w')
        self.canvas = tk.Canvas(body, height=210, bg='#142233', highlightthickness=0)
        self.canvas.pack(fill='both', expand=True, pady=12)
        ttk.Label(body, text='Cyan: PL yaw setting | Orange: PL pitch setting | readback, not external PWM measurement').pack(anchor='w')
        ttk.Label(body, text=f'Logs: {self.run_dir}').pack(anchor='w', pady=4)
        root.protocol('WM_DELETE_WINDOW', self.close)
        root.after(50, self.tick)

    def arm(self):
        if not self.sim and not all(self.profile[a]['verified'] is True for a in ('yaw', 'pitch')):
            messagebox.showerror('Motion locked', 'Both joints need measured safe limits and verified=true in the profile. Placeholder limits are not a calibration.')
            return
        if not self.synchronized or time.monotonic()-self.last_rx > .5:
            messagebox.showerror('No link', 'Fresh compatible telemetry is required. Rebuild PS firmware for the query extension.')
            return
        self.armed = True

    def stop(self):
        self.armed = False

    def center(self):
        for var, axis in zip(self.sliders, ('yaw', 'pitch')):
            var.set(self.profile[axis]['center_us'])

    def send(self, data, timestamp, now):
        self.sock.sendto(data, self.endpoint)
        self.pending[timestamp] = now
        self.pending = {k:v for k,v in self.pending.items() if now-v < 2}

    def tick(self):
        now = time.monotonic()
        try:
            # Commands and queries have separate timestamp keys even in one tick.
            if now-self.last_query >= .100:
                ts = int(now*1000) & 0xffffffff
                self.send(make_query(self.query_sequence, ts), ts, now)
                self.query_sequence = (self.query_sequence+1) & 0xffff
                self.last_query = now
            if self.armed and now-self.last_rx > .5:
                self.stop()
                self.synchronized = False
            if self.armed and now-self.last_tx >= .050:
                ts = (int(now*1000)+1) & 0xffffffff
                vals = []
                for var, axis in zip(self.sliders, ('yaw', 'pitch')):
                    p = self.profile[axis]
                    vals.append(max(p['min_us'], min(p['max_us'], var.get())))
                self.send(make_frame(self.sequence, *vals, ts), ts, now)
                self.sequence = (self.sequence+1) & 0xffff
                self.last_tx = now
            for _ in range(64):
                try:
                    raw, addr = self.sock.recvfrom(2048)
                except BlockingIOError:
                    break
                if addr != self.endpoint:
                    continue
                try:
                    state = parse_telemetry(raw)
                except ValueError:
                    continue
                sent = self.pending.pop(state['echo_timestamp_ms'], None)
                if sent is None or state['simulated'] != bool(self.sim):
                    continue
                received = time.monotonic()
                if not self.armed:
                    self.sequence = (state['sequence']+1) & 0xffff if state['have_sequence'] else 0
                self.synchronized = True
                self.last_rx = received
                self.last_good = state
                rtt = (received-sent)*1000
                self.rtts.append(rtt)
                self.writer.writerow(dict(state, elapsed_s=round(received-self.start_time, 4),
                                          mode=self.args.mode, rtt_ms=round(rtt, 3)))
                self.log.flush()
                self.points.append((state['output_yaw_us'], state['output_pitch_us']))
            link = now-self.last_rx < .5
            state = self.last_good
            rtt_text = f'{self.rtts[-1]:.1f} ms host-observed RTT' if self.rtts else 'no RTT'
            self.status_text.set(f"{'ONLINE' if link else 'NO FRESH TELEMETRY'} | {'ARMED' if self.armed else 'READ ONLY'} | {rtt_text}")
            if state:
                self.values_text.set(f"Target {state['target_yaw_us']:4d} / {state['target_pitch_us']:4d} us   PL output setting {state['output_yaw_us']:4d} / {state['output_pitch_us']:4d} us   Watchdog={bool(state['status'] & 2)}")
                self.counters_text.set(f"Accepted={state['accepted']} Invalid={state['invalid']} Stale={state['stale']} Watchdog events={state['watchdog_events']}")
            self.draw()
        except OSError as exc:
            self.stop()
            self.status_text.set(f'Network error / commands stopped: {exc}')
        self.root.after(25, self.tick)

    def draw(self):
        c = self.canvas
        c.delete('all')
        w, h = max(c.winfo_width(), 100), max(c.winfo_height(), 100)
        low = min(self.profile[a]['min_us'] for a in ('yaw', 'pitch'))-20
        high = max(self.profile[a]['max_us'] for a in ('yaw', 'pitch'))+20
        for pulse in (low, 1500, high):
            y = h-15-(pulse-low)/(high-low)*(h-30)
            c.create_line(42, y, w, y, fill='#34465a')
            c.create_text(20, y, text=str(pulse), fill='white')
        for axis, color in enumerate(('#39d8ee', '#ffa43b')):
            coords = []
            for i, p in enumerate(self.points):
                coords.extend((45+i*(w-50)/299, h-15-(p[axis]-low)/(high-low)*(h-30)))
            if len(coords) >= 4:
                c.create_line(*coords, fill=color, width=2)

    def close(self):
        self.stop()
        self.sock.close()
        if self.sim:
            self.sim.close()
        self.log.close()
        self.root.destroy()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--mode', choices=('sim', 'board'), default='sim')
    parser.add_argument('--host', default='192.168.10.20')
    parser.add_argument('--port', type=int, default=5005)
    parser.add_argument('--bind-ip', default='192.168.10.10')
    parser.add_argument('--profile', default=str(ROOT/'data/dashboard_profile.json'))
    args = parser.parse_args()
    root = tk.Tk()
    try:
        Dashboard(root, args)
    except (OSError, ValueError) as exc:
        messagebox.showerror('NeuroHead connection/configuration error',
                             f'{exc}\nBoard mode requires the PC Ethernet address {args.bind_ip}.')
        root.destroy()
        return
    root.mainloop()


if __name__ == '__main__':
    main()
