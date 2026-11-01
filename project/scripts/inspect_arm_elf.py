"""Read symbols from little-endian ARM ELF32 without executing a binary."""
import argparse
import json
from pathlib import Path
import struct


def inspect(path):
    data = Path(path).read_bytes()
    if data[:7] != b'\x7fELF\x01\x01\x01':
        raise ValueError('Expected little-endian ELF32')
    header = struct.unpack_from('<HHIIIIIHHHHHH', data, 16)
    if header[1] != 40:
        raise ValueError('Expected ARM machine type')
    entry, shoff, shentsize, shnum = header[3], header[5], header[10], header[11]
    sections = [struct.unpack_from('<IIIIIIIIII', data, shoff+i*shentsize) for i in range(shnum)]
    names = ('_vector_table','_boot','_start','main','MMUTable', 'server_netif',
             'last_sequence','have_last_sequence','valid_command_count',
             'invalid_frame_count','stale_sequence_count','neurohead_boot_stage')
    symbols = {}
    mmu = None
    for section in sections:
        if section[1] != 2:
            continue
        strings_section = sections[section[6]]
        strings = data[strings_section[4]:strings_section[4]+strings_section[5]]
        for offset in range(section[4], section[4]+section[5], section[9]):
            name_offset, value, size, _, _, section_index = struct.unpack_from('<IIIBBH', data, offset)
            end = strings.find(b'\0', name_offset)
            name = strings[name_offset:end].decode('ascii', errors='replace')
            if name in names:
                symbols[name] = dict(address=f'0x{value:08x}', size=size)
            if name == 'MMUTable':
                mapped = sections[section_index]
                table_offset = mapped[4] + value - mapped[3]
                pl_word = struct.unpack_from('<I', data, table_offset+0x400*4)[0]
                mmu = dict(address=f'0x{value:08x}', aligned_16kb=(value & 0x3fff) == 0,
                           section_size=mapped[5], pl_section_descriptor=f'0x{pl_word:08x}')
    return dict(file=str(path), entry=f'0x{entry:08x}', symbols=symbols, mmu_table=mmu)


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('elf')
    p.add_argument('--check-startup', action='store_true')
    args = p.parse_args()
    result = inspect(args.elf)
    print(json.dumps(result, indent=2))
    if args.check_startup:
        mmu = result['mmu_table']
        good = (result['entry'] == '0x01000000'
                and result['symbols'].get('_vector_table', {}).get('address') == result['entry']
                and mmu is not None and mmu['aligned_16kb'] and mmu['section_size'] == 0x4000
                and int(mmu['pl_section_descriptor'], 16) & 0xfff00000 == 0x40000000)
        if not good:
            raise SystemExit('ELF_STARTUP_CHECK_FAIL: verify entry point and MMU table alignment/mapping')
        print('ELF_STARTUP_CHECK_PASS')
