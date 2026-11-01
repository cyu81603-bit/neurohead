"""Loopback UDP functional model. This does NOT validate RTL or board timing."""
import socket
import struct
import threading
import time
from monitor_protocol import make_telemetry, parse_query, valid_crc


class BoardModel:
    def __init__(self, now=0.0):
        self.targets = [1500, 1500]
        self.outputs = [1500, 1500]
        self.sequence = 0
        self.have_sequence = False
        self.accepted = self.invalid = self.stale = self.watchdog_events = 0
        self.last_command = now
        self.last_tick = now
        self.watchdog = False
        self.safe = True

    def advance(self, now):
        # Advance at frame boundaries; this is an approximate functional model.
        while self.last_tick + .020 <= now + 1e-9:
            self.last_tick += .020
            timeout = self.last_tick - self.last_command >= .300 - 1e-9
            if timeout and not self.watchdog:
                self.watchdog_events += 1
            self.watchdog = timeout
            self.safe = timeout or not self.have_sequence
            goals = [1500, 1500] if self.safe else self.targets
            self.outputs = [v + max(-8, min(8, t-v)) for v, t in zip(self.outputs, goals)]

    def reply(self, timestamp, query):
        return make_telemetry(self.sequence, int(self.safe) | int(self.watchdog) << 1,
                              self.targets, self.outputs, self.accepted, self.invalid,
                              self.stale, self.watchdog_events, timestamp,
                              simulated=True, query=query, have_sequence=self.have_sequence)

    def receive(self, data, now):
        self.advance(now)
        try:
            _, timestamp = parse_query(data)
            return self.reply(timestamp, True)
        except ValueError:
            pass
        valid = (len(data) == 16 and data[:3] == b'NH\x01'
                 and data[3] & 1 and valid_crc(data))
        if valid:
            seq, yaw, pitch, timestamp = struct.unpack_from('<HHHI', data, 4)
            valid = 600 <= yaw <= 2400 and 600 <= pitch <= 2400
        if not valid:
            self.invalid += 1
            return None
        delta = (seq - self.sequence) & 0xffff
        if self.have_sequence and not 0 < delta < 0x8000:
            self.stale += 1
            return None
        self.sequence, self.targets = seq, [yaw, pitch]
        self.have_sequence = True
        self.accepted += 1
        self.last_command = now
        self.safe = self.watchdog = False
        return self.reply(timestamp, False)


class SimulatedBoard:
    def __init__(self):
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.bind(('127.0.0.1', 0))
        self.address = self.sock.getsockname()
        self.sock.settimeout(.02)
        self.stop_event = threading.Event()
        self.thread = threading.Thread(target=self.run, daemon=True)

    def start(self):
        self.thread.start()
        return self.address

    def run(self):
        model = BoardModel(time.monotonic())
        while not self.stop_event.is_set():
            try:
                data, addr = self.sock.recvfrom(2048)
                reply = model.receive(data, time.monotonic())
                if reply is not None:
                    self.sock.sendto(reply, addr)
            except socket.timeout:
                model.advance(time.monotonic())
            except OSError:
                break

    def close(self):
        self.stop_event.set()
        self.thread.join(timeout=.5)
        self.sock.close()
