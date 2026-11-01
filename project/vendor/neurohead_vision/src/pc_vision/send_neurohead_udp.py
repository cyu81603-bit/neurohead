#!/usr/bin/env python3
"""Build or explicitly send one NeuroHead UDP control frame."""
import argparse
import socket
import struct

MAGIC = b"NH"
PORT = 5005


def crc16_ccitt_false(data: bytes) -> int:
    crc = 0xFFFF
    for byte in data:
        crc ^= byte << 8
        for _ in range(8):
            crc = ((crc << 1) ^ 0x1021) & 0xFFFF if crc & 0x8000 else (crc << 1) & 0xFFFF
    return crc


def make_frame(sequence: int, yaw_us: int, pitch_us: int, timestamp_ms: int) -> bytes:
    if not (600 <= yaw_us <= 2400 and 600 <= pitch_us <= 2400):
        raise ValueError("yaw_us and pitch_us must each be between 600 and 2400")
    payload = MAGIC + bytes((1, 1)) + struct.pack("<HHH", sequence, yaw_us, pitch_us) + struct.pack("<I", timestamp_ms)
    return payload + struct.pack("<H", crc16_ccitt_false(payload))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="192.168.10.20")
    parser.add_argument("--yaw", type=int, default=1500)
    parser.add_argument("--pitch", type=int, default=1500)
    parser.add_argument("--sequence", type=int, default=1)
    parser.add_argument("--timestamp-ms", type=int, default=0)
    parser.add_argument("--send", action="store_true", help="actually transmit; without this only print the frame")
    args = parser.parse_args()
    frame = make_frame(args.sequence, args.yaw, args.pitch, args.timestamp_ms)
    print(f"{len(frame)} bytes: {frame.hex(' ')}")
    if args.send:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.sendto(frame, (args.host, PORT))
        print(f"sent to {args.host}:{PORT}")


if __name__ == "__main__":
    main()
