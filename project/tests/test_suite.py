"""Offline regression. Temporary data is synthetic; no board, network or PYNQ import."""
import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[1]


def module(skill, script):
    spec = importlib.util.spec_from_file_location(script, ROOT/'skill'/skill/'scripts'/(script+'.py'))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


overlay = module('pynq-overlay', 'overlay_guard')
dma_helper = module('pynq-dma', 'dma_transfer')
generator = module('pynq-interface', 'generate_host')
manifest = module('fpga-evidence', 'manifest')
golden = module('fpga-evidence', 'golden_report')
implementation = module('fpga-evidence', 'implementation_report')
benchmark = module('fpga-evidence', 'benchmark')
trial = module('fpga-commissioning', 'trial_evidence')


class OverlayTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.bit = self.root/'test.bit'
        self.bit.write_bytes(b'synthetic-not-a-bitstream')
        self.bit.with_suffix('.hwh').write_text('<ROOT><MODULE FULLNAME="/accel_0" VLNV="x:y:z:1"/></ROOT>')
        self.manifest = self.root/'trusted.json'
        self.manifest.write_text(json.dumps({'files': {p.name: overlay.sha256(p)
                                                     for p in (self.bit, self.bit.with_suffix('.hwh'))}}))

    def test_offline_hash_and_ip(self):
        result = overlay.inspect_bundle(self.bit, ['accel_0'], self.manifest)
        self.assertTrue(result['trusted_hashes_verified'])
        self.assertIn('accel_0', result['hwh_modules'])

    def test_hash_corruption(self):
        self.bit.write_bytes(b'changed')
        with self.assertRaises(ValueError): overlay.inspect_bundle(self.bit, [], self.manifest)

    def test_missing_hwh(self):
        self.bit.with_suffix('.hwh').unlink()
        with self.assertRaises(ValueError): overlay.inspect_bundle(self.bit)

    def test_missing_ip(self):
        with self.assertRaises(ValueError): overlay.inspect_bundle(self.bit, ['wrong'])

    def test_download_after_metadata(self):
        events = []
        class FakeOverlay:
            def __init__(self, path, download):
                self.ip_dict = {'accel_0': {'phys_addr': 0x40000000, 'addr_range': 4096}}
                events.append(('parse', download))
            def download(self): events.append(('download', True))
            def is_loaded(self): return True
        _, report = overlay.load_overlay(self.bit, ['accel_0'], self.manifest, FakeOverlay)
        self.assertEqual(events, [('parse', False), ('download', True)])
        self.assertFalse(report['hardware_identity_verified'])

    def test_loading_requires_trust(self):
        with self.assertRaises(ValueError): overlay.load_overlay(self.bit, ['accel_0'])


class Buffer:
    def __init__(self, addr, events, name, nbytes=16):
        self.device_address, self.nbytes = addr, nbytes
        self.flags = SimpleNamespace(c_contiguous=True)
        self.events, self.name, self.freed = events, name, False
    def flush(self): self.events.append(self.name+'.flush')
    def invalidate(self): self.events.append(self.name+'.invalidate')
    def freebuffer(self): self.freed = True


class Channel:
    def __init__(self, name, events, behavior):
        self.name, self.events, self.behavior = name, events, behavior
        self.idle, self.running, self.error, self.transferred = True, True, False, 0
    def transfer(self, buf):
        self.events.append(self.name+'.transfer')
        self.idle = self.behavior not in ('timeout', 'error')
        self.error = self.behavior == 'error'
        self.transferred = buf.nbytes if self.behavior != 'short' else buf.nbytes-1
    def wait(self):
        if not self.idle: raise AssertionError('unbounded wait entered')
        self.events.append(self.name+'.wait')
    def stop(self):
        self.events.append(self.name+'.stop')
        self.running = False


class DMATests(unittest.TestCase):
    def fixture(self, behavior='good'):
        events = []
        dma = SimpleNamespace(sendchannel=Channel('send', events, behavior),
                              recvchannel=Channel('recv', events, behavior),
                              description={'parameters': {'c_include_sg': '0', 'c_micro_dma': '0'}})
        return dma, Buffer(0x1000, events, 'tx'), Buffer(0x2000, events, 'rx'), events

    def exchange(self, dma, tx, rx, **kw):
        args = dict(timeout=.005, max_bytes=1024, tx_word_bytes=4, rx_word_bytes=4,
                    tx_dre=False, rx_dre=False, poll_seconds=.001)
        args.update(kw)
        return dma_helper.exchange(dma, tx, rx, **args)

    def test_receive_first_and_cache_order(self):
        dma, tx, rx, events = self.fixture()
        result = self.exchange(dma, tx, rx, start_ip=lambda: events.append('ip.start'))
        self.assertLess(events.index('tx.flush'), events.index('send.transfer'))
        self.assertLess(events.index('recv.transfer'), events.index('ip.start'))
        self.assertLess(events.index('ip.start'), events.index('send.transfer'))
        self.assertGreater(events.index('rx.invalidate'), events.index('recv.wait'))
        self.assertEqual(result['bytes_per_direction'], 16)

    def test_timeout_retains_buffers_and_stops(self):
        dma, tx, rx, events = self.fixture('timeout')
        with self.assertRaises(dma_helper.TransferFailure) as caught: self.exchange(dma, tx, rx)
        self.assertEqual(caught.exception.buffers, (tx, rx))
        self.assertFalse(tx.freed or rx.freed)
        self.assertIn('send.stop', events)
        self.assertIn('recv.stop', events)
        self.assertNotIn('recv.wait', events)

    def test_device_error(self):
        dma, tx, rx, _ = self.fixture('error')
        with self.assertRaises(dma_helper.TransferFailure): self.exchange(dma, tx, rx)

    def test_short_frame(self):
        dma, tx, rx, _ = self.fixture('short')
        with self.assertRaises(dma_helper.TransferFailure): self.exchange(dma, tx, rx)

    def test_length_alignment_and_overlap(self):
        for change in ('zero', 'large', 'unaligned', 'overlap', 'mismatch'):
            with self.subTest(change=change):
                dma, tx, rx, events = self.fixture()
                if change == 'zero': tx.nbytes = 0
                if change == 'large': tx.nbytes = 2048
                if change == 'unaligned': tx.device_address += 1
                if change == 'overlap': rx.device_address = tx.device_address+4
                if change == 'mismatch': rx.nbytes = 12
                with self.assertRaises(ValueError): self.exchange(dma, tx, rx)
                self.assertFalse(events)

    def test_no_plain_array_and_nan_timeout(self):
        dma, tx, rx, _ = self.fixture()
        with self.assertRaises(TypeError): self.exchange(dma, object(), rx)
        with self.assertRaises(ValueError): self.exchange(dma, tx, rx, timeout=float('nan'))

    def test_busy_rejected_before_io(self):
        dma, tx, rx, events = self.fixture()
        dma.sendchannel.idle = False
        with self.assertRaises(ValueError): self.exchange(dma, tx, rx)
        self.assertFalse(events)

    def test_initial_idle_low_allowed_only_by_driver_flag(self):
        dma, tx, rx, _ = self.fixture()
        for channel in (dma.sendchannel, dma.recvchannel):
            channel.idle = False
            channel._first_transfer = True
        self.assertEqual(self.exchange(dma, tx, rx)['bytes_per_direction'], 16)

    def test_sg_micro_and_missing_config_rejected(self):
        for parameters in ({}, {'c_include_sg':'1', 'c_micro_dma':'0'},
                           {'c_include_sg':'0', 'c_micro_dma':'1'}):
            dma, tx, rx, events = self.fixture()
            dma.description['parameters'] = parameters
            with self.assertRaises(ValueError): self.exchange(dma, tx, rx)
            self.assertFalse(events)


class GeneratorTests(unittest.TestCase):
    def contract(self):
        return json.loads((ROOT/'skill/pynq-interface/assets/interface.example.json').read_text())

    def test_two_unrelated_contracts_generate_and_execute(self):
        vector = self.contract()
        sensor = dict(schema_version=1, ip_path='hier/temperature',
                      vlnv='demo:user:temperature:2.0', address_range=256,
                      registers=[dict(name='TEMP_MILLI_C', offset=64, width=24, access='ro', unit='milli_C'),
                                 dict(name='PERIOD_MS', offset=80, width=16, access='rw', unit='ms')])
        for data in (vector, sensor):
            with self.subTest(ip=data['ip_path']), tempfile.TemporaryDirectory() as folder:
                path = Path(folder)/'contract.json'
                path.write_text(json.dumps(data))
                output = Path(folder)/'generated'
                generator.generate(path, output)
                result = subprocess.run([sys.executable, '-B', '-m', 'unittest', 'discover', '-s', str(output), '-v'],
                                        capture_output=True, text=True)
                self.assertEqual(result.returncode, 0, result.stderr)

    def test_contract_rejects_unsafe_semantics_and_offsets(self):
        for update in ({'offset': 1}, {'offset': 4096}, {'name': 'a;exec'},
                       {'access': 'clear-on-read'}, {'width': 64}, {'unit': ''}):
            with self.subTest(update=update):
                data = self.contract()
                data['registers'][0].update(update)
                with self.assertRaises(ValueError): generator.validate(data)

    def test_overlap_and_duplicates(self):
        for key in ('name', 'offset'):
            data = self.contract()
            data['registers'][1][key] = data['registers'][0][key]
            with self.assertRaises(ValueError): generator.validate(data)

    def test_output_not_overwritten(self):
        with tempfile.TemporaryDirectory() as folder:
            contract = ROOT/'skill/pynq-interface/assets/interface.example.json'
            generator.generate(contract, folder)
            with self.assertRaises(FileExistsError): generator.generate(contract, folder)


class ManifestTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)/'root'
        self.root.mkdir()
        self.file = self.root/'asset.bin'
        self.file.write_bytes(b'original')
        self.path = Path(self.temp.name)/'trusted.json'
        manifest.create(self.root, self.path)

    def test_good_corrupt_missing(self):
        self.assertEqual(manifest.verify(self.root, self.path)['verified_files'], 1)
        self.file.write_bytes(b'corrupt')
        with self.assertRaises(ValueError): manifest.verify(self.root, self.path)
        self.file.unlink()
        with self.assertRaises(ValueError): manifest.verify(self.root, self.path)

    def test_path_escape_absolute_and_aliases(self):
        for name in ('../escape', '/absolute', 'C:/absolute', 'a/../asset.bin', 'a\\b', 'asset.bin:stream'):
            self.path.write_text(json.dumps({'files': {name: '0'*64}}))
            with self.subTest(name=name), self.assertRaises(ValueError): manifest.verify(self.root, self.path)

    def test_extra_files_strict(self):
        (self.root/'extra').write_text('extra')
        self.assertEqual(manifest.verify(self.root, self.path)['unlisted_files'], ['extra'])
        with self.assertRaises(ValueError): manifest.verify(self.root, self.path, strict=True)

    def test_empty_and_self_containing_manifest(self):
        self.path.write_text('{"files":{}}')
        with self.assertRaises(ValueError): manifest.verify(self.root, self.path)
        with self.assertRaises(ValueError): manifest.create(self.root, self.root/'manifest.json')


class GoldenTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
    def write(self, name, text):
        path = self.root/name
        path.write_text(text)
        return path

    def test_numeric_tolerance_and_failure_coordinates(self):
        e = self.write('expected.csv', 'x,y\n1,0\n2,3\n')
        a = self.write('actual.csv', 'x,y\n1.0001,0\n2,3\n')
        self.assertTrue(golden.compare(e, a, atol=.001)['passed'])
        failure = golden.compare(e, a)
        self.assertFalse(failure['passed'])
        self.assertEqual(failure['first_failures'][0]['row'], 2)

    def test_nan_inf_ragged_empty_and_shape(self):
        expected = self.write('expected.csv', 'x\n1\n')
        for text in ('x\nnan\n', 'x\ninf\n', 'x\n1,2\n', 'x\n', 'y\n1\n', 'x\n1\n2\n'):
            with self.subTest(text=text), self.assertRaises(ValueError):
                golden.compare(expected, self.write('actual.csv', text))

    def test_latency_statistics(self):
        expected = self.write('e.csv', 'x\n0\n')
        latency = self.write('l.csv', 'latency_ms\n1\n2\n3\n4\n5\n')
        result = golden.compare(expected, expected, latency=latency)
        self.assertEqual(result['latency']['median_ms'], 3)
        self.assertEqual(result['latency']['p95_ms'], 5)

    def test_bad_tolerance_and_negative_latency(self):
        expected = self.write('e.csv', 'x\n0\n')
        with self.assertRaises(ValueError): golden.compare(expected, expected, atol=-1)
        with self.assertRaises(ValueError):
            golden.compare(expected, expected, latency=self.write('l.csv', 'latency_ms\n-1\n'))


class BenchmarkTests(unittest.TestCase):
    def test_collect_command_timings_and_outputs(self):
        with tempfile.TemporaryDirectory() as folder:
            out = Path(folder)/'run'
            result = benchmark.measure([sys.executable, '-c', 'print(sum(range(100)))'], out,
                                       samples=2, warmups=1)
            self.assertTrue(result['passed'])
            self.assertEqual(result['completed_samples'], 2)
            self.assertEqual(len(result['runs']), 3)
            self.assertEqual((out/'run-0000.stdout').read_text().strip(), '4950')
            self.assertEqual(len((out/'latency.csv').read_text().splitlines()), 3)

    def test_failed_command_is_preserved_and_stops(self):
        with tempfile.TemporaryDirectory() as folder:
            result = benchmark.measure([sys.executable, '-c', 'raise SystemExit(2)'], Path(folder)/'run', samples=3)
            self.assertFalse(result['passed'])
            self.assertEqual(result['completed_samples'], 0)
            self.assertEqual(len(result['runs']), 1)
            self.assertEqual(result['runs'][0]['returncode'], 2)


TIMING = '''| Tool Version : Vivado synthetic
| Design : unrelated_design
| Device : 7z020-clg400
| Design State : Routed
checking no_clock (0)
checking unconstrained_internal_endpoints (0)
checking no_input_delay (0)
checking no_output_delay (0)
checking partial_input_delay (0)
checking partial_output_delay (0)
WNS(ns) TNS(ns) TNS Failing Endpoints TNS Total Endpoints WHS(ns) THS(ns) THS Failing Endpoints THS Total Endpoints WPWS(ns) TPWS(ns) TPWS Failing Endpoints TPWS Total Endpoints
------- ------- -------- ------ ------- ------ ------ ------ ------ ------ ------ ------
1.000 0.000 0 100 0.100 0.000 0 100 2.000 0.000 0 100
| Clock Summary
Clock Waveform(ns) Period(ns) Frequency(MHz)
other_clk {0.000 5.000} 10.000 100.000
second_clk {0.000 10.000} 20.000 50.000
| Intra Clock Table
'''
UTIL = '''| Tool Version : Vivado synthetic
| Design : unrelated_design
| Device : xc7z020clg400-2
| Design State : Routed
| CLB LUTs | 123 | 0 |
| CLB Registers | 456 | 0 |
| Block RAM Tile | 0.5 | 0 |
| DSPs | 2 | 0 |
'''


class ImplementationTests(unittest.TestCase):
    def parse(self, timing=TIMING, util=UTIL):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root/'timing_summary.rpt').write_text(timing)
            (root/'utilization.rpt').write_text(util)
            return implementation.parse(root)

    def test_multiclock_and_fractional_bram(self):
        report = self.parse()
        self.assertEqual(len(report['clocks']), 2)
        self.assertEqual(report['resources']['bram_tiles'], .5)
        self.assertTrue(implementation.evaluate(report)['passed'])

    def test_hold_failure_and_resource_budget(self):
        report = self.parse(TIMING.replace('0.100 0.000 0', '-0.100 -1.000 1'))
        self.assertFalse(implementation.evaluate(report)['passed'])
        self.assertFalse(implementation.evaluate(self.parse(), max_luts=100)['passed'])

    def test_constraint_gap_and_explicit_waiver(self):
        report = self.parse(TIMING.replace('no_output_delay (0)', 'no_output_delay (22)'))
        self.assertFalse(implementation.evaluate(report)['passed'])
        self.assertTrue(implementation.evaluate(report, constraint_waiver='reviewed asynchronous test outputs')['passed'])
        report = self.parse(TIMING.replace('no_clock (0)', 'no_clock (1)'))
        self.assertFalse(implementation.evaluate(report, constraint_waiver='cannot waive missing clock')['passed'])

    def test_unknown_format_or_identity_mismatch(self):
        for timing, util in [('unknown', UTIL), (TIMING, UTIL.replace('unrelated_design', 'different')),
                             (TIMING, UTIL.replace('7z020', '7z010'))]:
            with self.subTest(timing=timing[:10]), self.assertRaises(ValueError): self.parse(timing, util)

    def test_real_r6_7_report_does_not_hide_io_gap(self):
        report = implementation.parse(ROOT/'validation/source-reports')
        self.assertEqual(report['resources']['luts'], 7033)
        self.assertAlmostEqual(report['wns_ns'], 5.432)
        self.assertEqual(report['constraint_checks']['no_output_delay'], 22)
        self.assertFalse(implementation.evaluate(report)['passed'])


class TrialTests(unittest.TestCase):
    def fixture(self):
        return json.loads((ROOT/'skill/fpga-commissioning/assets/digital-only.example.json').read_text())

    def test_digital_does_not_imply_physical(self):
        data = self.fixture()
        self.assertTrue(trial.audit(data, 1005)['claims_consistent'])
        data['claims'].append('physical_motion_verified')
        self.assertFalse(trial.audit(data, 1005)['claims_consistent'])

    def test_simulation_cannot_certify_motion(self):
        data = self.fixture()
        data['evidence']['physical_motion'] = dict(verified=True, source='fake_observation')
        data['claims'] = ['physical_motion_verified']
        self.assertFalse(trial.audit(data, 1005)['claims_consistent'])

    def test_stale_changed_build_and_profile(self):
        for key, value in [('current_build_id', 'new-build'), ('current_profile_sha256', 'b'*64),
                           ('captured_at_epoch', 900), ('captured_at_epoch', 1010)]:
            data = self.fixture()
            data[key] = value
            with self.subTest(key=key), self.assertRaises(ValueError): trial.audit(data, 1005)

    def test_closed_loop_requires_sensor_and_motion(self):
        data = self.fixture()
        data['mode'] = 'hardware'
        data['claims'] = ['closed_loop_error_measured']
        data['evidence']['physical_motion'] = dict(verified=True, source='operator-log')
        self.assertFalse(trial.audit(data, 1005)['claims_consistent'])
        data['evidence']['closed_loop_sensor'] = dict(verified=True, source='encoder-log')
        self.assertTrue(trial.audit(data, 1005)['claims_consistent'])


if __name__ == '__main__':
    unittest.main(verbosity=2)
