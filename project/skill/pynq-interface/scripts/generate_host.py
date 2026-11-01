"""Generate a small register API from a validated JSON contract; no board IO."""
import argparse
import json
import keyword
from pathlib import Path
import re


def validate(data):
    if data.get('schema_version') != 1:
        raise ValueError('schema_version must be 1')
    for key in ('ip_path', 'vlnv'):
        if not isinstance(data.get(key), str) or not data[key].strip():
            raise ValueError('missing ' + key)
    size = data.get('address_range')
    if type(size) is not int or size < 4 or size % 4:
        raise ValueError('address_range must be a multiple of 4')
    regs = data.get('registers')
    if not isinstance(regs, list) or not regs:
        raise ValueError('nonempty registers required')
    names, offsets = set(), set()
    for reg in regs:
        name = reg.get('name', '')
        if not isinstance(name, str) or not re.fullmatch(r'[A-Za-z][A-Za-z0-9_]*', name) or keyword.iskeyword(name):
            raise ValueError('invalid register identifier')
        offset, width = reg.get('offset'), reg.get('width')
        if type(offset) is not int or offset < 0 or offset % 4 or offset + 4 > size:
            raise ValueError('invalid register offset')
        if type(width) is not int or not 1 <= width <= 32:
            raise ValueError('only 1..32 bit registers supported')
        if reg.get('access') not in ('ro', 'rw', 'wo', 'w1c'):
            raise ValueError('unsupported register semantics')
        if not isinstance(reg.get('unit'), str) or not reg['unit']:
            raise ValueError('explicit unit required')
        if name in names or offset in offsets:
            raise ValueError('duplicate name/overlapping register')
        names.add(name)
        offsets.add(offset)
    return data


def generate(contract, output):
    data = validate(json.loads(Path(contract).read_text(encoding='utf-8-sig')))
    out = Path(output)
    targets = [out / 'host_api.py', out / 'test_host_api.py']
    if any(p.exists() for p in targets):
        raise FileExistsError('refuse to overwrite generated files')
    api = ['"""Generated register access only; no implicit writes or hardware loading."""',
           'CONTRACT = ' + repr(data), '', 'class RegisterAPI:',
           '    def __init__(self, ip):', '        self.ip = ip', '']
    tests = ['import unittest', 'from host_api import RegisterAPI', '',
             'class MockIP:', '    def __init__(self):', '        self.calls = []',
             '    def read(self, offset):', "        self.calls.append(('read', offset))",
             '        return 0xffffffff', '    def write(self, offset, value):',
             "        self.calls.append(('write', offset, value))", '',
             'class ContractTest(unittest.TestCase):']
    for reg in data['registers']:
        name, offset, access = reg['name'], reg['offset'], reg['access']
        mask = (1 << reg['width']) - 1
        if access in ('ro', 'rw'):
            api += [f'    def read_{name}(self):',
                    f'        return self.ip.read({offset}) & {mask}', '']
        if access in ('rw', 'wo', 'w1c'):
            api += [f'    def write_{name}(self, value):',
                    f'        if type(value) is not int or not 0 <= value <= {mask}:',
                    "            raise ValueError('register value outside contract')",
                    f'        self.ip.write({offset}, value)', '']
        tests += [f'    def test_{name}(self):', '        ip = MockIP()',
                  '        api = RegisterAPI(ip)']
        if access in ('ro', 'rw'):
            tests += [f'        self.assertEqual(api.read_{name}(), {mask})',
                      f"        self.assertEqual(ip.calls, [('read', {offset})])", '        ip.calls.clear()']
        else:
            tests += [f"        self.assertFalse(hasattr(api, 'read_{name}'))"]
        if access in ('rw', 'wo', 'w1c'):
            tests += [f'        api.write_{name}({mask})',
                      f"        self.assertEqual(ip.calls, [('write', {offset}, {mask})])",
                      '        for bad in (-1, ' + str(mask + 1) + ', True, 1.5):',
                      '            with self.assertRaises(ValueError):',
                      f'                api.write_{name}(bad)']
        else:
            tests += [f"        self.assertFalse(hasattr(api, 'write_{name}'))"]
        tests += ['']
    tests += ["if __name__ == '__main__':", '    unittest.main(verbosity=2)', '']
    out.mkdir(parents=True, exist_ok=True)
    targets[0].write_text('\n'.join(api), encoding='utf-8')
    targets[1].write_text('\n'.join(tests), encoding='utf-8')
    return targets


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('contract')
    parser.add_argument('output')
    args = parser.parse_args()
    for path in generate(args.contract, args.output):
        print(path)
