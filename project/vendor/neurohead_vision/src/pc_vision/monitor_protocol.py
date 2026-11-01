"""Read-only query / telemetry extension; legacy 16-byte commands stay unchanged."""
import struct
from send_neurohead_udp import crc16_ccitt_false


def _crc(data):
    return data + struct.pack('<H', crc16_ccitt_false(data))


def make_query(sequence, timestamp_ms):
    return _crc(struct.pack('<2sBBHI', b'NQ', 1, 0, sequence, timestamp_ms))


def valid_crc(data):
    return len(data) >= 2 and struct.unpack_from('<H', data, len(data)-2)[0] == crc16_ccitt_false(data[:-2])


def parse_query(data):
    if len(data) != 12 or data[:4] != b'NQ\x01\x00' or not valid_crc(data):
        raise ValueError('Invalid read-only query')
    return struct.unpack_from('<HI', data, 4)


def make_telemetry(sequence, status, targets, outputs, accepted, invalid, stale,
                   watchdog_events, timestamp_ms, simulated=False, query=False,
                   have_sequence=True):
    flags = int(simulated) | (int(query) << 1) | (int(have_sequence) << 2)
    payload = struct.pack('<2sBBHHHHHHIIIIIH', b'NT', 1, flags, sequence, status,
                          *targets, *outputs, accepted, invalid, stale,
                          watchdog_events, timestamp_ms, 0)
    return _crc(payload)


def parse_telemetry(data):
    if len(data) != 40 or data[:3] != b'NT\x01' or not valid_crc(data):
        raise ValueError('Invalid telemetry length, version or CRC')
    if data[3] & ~7 or data[36:38] != b'\0\0':
        raise ValueError('Unsupported telemetry flags/reserved field')
    fields = struct.unpack('<2sBBHHHHHHIIIIIHH', data)
    keys = ('sequence', 'status', 'target_yaw_us', 'target_pitch_us',
            'output_yaw_us', 'output_pitch_us', 'accepted', 'invalid',
            'stale', 'watchdog_events', 'echo_timestamp_ms')
    result = dict(zip(keys, fields[3:16]))
    result.update(simulated=bool(fields[2] & 1), query=bool(fields[2] & 2),
                  have_sequence=bool(fields[2] & 4))
    return result
