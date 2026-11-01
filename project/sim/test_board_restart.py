import contextlib,json,shutil,subprocess,sys,tempfile,time,unittest
from pathlib import Path
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'src/pc'))
import board_restart as app
class FakeCommands:
    def __init__(self,queries=None,load='ok'):self.calls=[];self.queries=list(queries or ['ok']);self.load=load
    def __call__(self,args,timeout=120):
        parts=[str(x) for x in args];self.calls.append(parts)
        if any(x.endswith('load_22.ps1') for x in parts):
            return subprocess.CompletedProcess(args,1 if self.load=='fail' else 0,'MONITOR_BINARY_JTAG_LAUNCHED: fake' if self.load=='ok' else 'no marker','')
        if any(x.endswith('probe_board.py') for x in parts):
            kind=self.queries.pop(0)
            if kind=='timeout':return subprocess.CompletedProcess(args,1,'','TimeoutError: timed out')
            if kind=='protocol':return subprocess.CompletedProcess(args,1,'','invalid v2 telemetry')
            result=dict(read_only=True,motion_commands_sent=0,configuration_commands_sent=0,successful_queries=10,last=dict(status=1 if kind=='active' else 0,active_mask=1 if kind=='active' else 0,configured_mask=7 if kind=='configured' else 0))
            if kind=='bad':result['motion_commands_sent']=1
            Path(parts[parts.index('--out')+1]).write_text(json.dumps(result),encoding='utf-8')
            return subprocess.CompletedProcess(args,0,'query ok','')
        if any(x.endswith('recover_cold_network.tcl') for x in parts):return subprocess.CompletedProcess(args,0,'COLD_START_RESUME_OK','')
        return subprocess.CompletedProcess(args,0,'NETWORK_READY','')
class Engine(app.BoardRecovery):
    def check_dependencies(self):self.shell='fake-pwsh'
class RecoveryTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.root=Path(self.temp.name);(self.root/'build').mkdir();self.commands=FakeCommands()
    def engine(self,commands=None,**kwargs):return Engine(self.root,runner=commands or self.commands,controllers=kwargs.pop('controllers',lambda:[]),lock_factory=kwargs.pop('lock_factory',lambda _:contextlib.nullcontext()),**kwargs)
    def test_missing_confirmation_blocks_all_commands(self):
        for flags in ((False,True,True),(True,False,True),(True,True,False)):
            with self.assertRaises(app.RecoveryError):self.engine().recover(*flags)
        self.assertFalse(self.commands.calls)
    def test_live_controller_blocks_programming(self):
        with self.assertRaises(app.RecoveryError):self.engine(controllers=lambda:[dict(pid=1,mode='paused')]).recover(True,True,True)
        self.assertFalse(self.commands.calls)
    def test_busy_lock_blocks_programming(self):
        def busy(_):raise OSError('lock busy')
        with self.assertRaises(app.RecoveryError):self.engine(lock_factory=busy).recover(True,True,True)
        self.assertFalse(self.commands.calls)
    def test_normal_recovery_only_queries_after_authenticated_load(self):
        r=self.engine().recover(True,True,True);self.assertTrue(r['pwm_disabled']);self.assertFalse(r['cold_network_recovered']);self.assertEqual(len(self.commands.calls),3)
        self.assertIn('-RecoveryAssetsOnly',self.commands.calls[1]);self.assertIn('--expect-disabled',self.commands.calls[2])
        self.assertTrue(Path(r['log_path']).exists())
    def test_load_failure_or_missing_marker_blocks_query(self):
        for status in ('fail','no_marker'):
            c=FakeCommands(load=status)
            with self.assertRaises(app.RecoveryError):self.engine(c).recover(True,True,True)
            self.assertEqual(len(c.calls),2)
    def test_timeout_allows_one_cold_resume_and_then_requires_query(self):
        c=FakeCommands(['timeout','ok']);r=self.engine(c).recover(True,True,True)
        self.assertTrue(r['cold_network_recovered']);self.assertEqual(sum(any(x.endswith('recover_cold_network.tcl') for x in a) for a in c.calls),1)
        self.assertEqual(len(c.calls),5)
    def test_second_timeout_does_not_loop(self):
        c=FakeCommands(['timeout','timeout'])
        with self.assertRaises(app.CommunicationError):self.engine(c).recover(True,True,True)
        self.assertEqual(len(c.calls),5)
    def test_active_or_invalid_telemetry_never_triggers_cpu_recovery(self):
        for kind in ('active','bad','protocol'):
            c=FakeCommands([kind])
            with self.assertRaises(app.RecoveryError):self.engine(c).recover(True,True,True)
            self.assertEqual(len(c.calls),3)
    def test_check_only_never_loads_or_recovers_cpu(self):
        c=FakeCommands(['configured']);r=self.engine(c).recover(check_only=True)
        self.assertTrue(r['check_only']);self.assertEqual(len(c.calls),2);self.assertIn('-CheckOnly',c.calls[0]);self.assertNotIn('--expect-disabled',c.calls[1])
    def test_check_only_timeout_does_not_reset_board(self):
        c=FakeCommands(['timeout'])
        with self.assertRaises(app.CommunicationError):self.engine(c).recover(check_only=True)
        self.assertEqual(len(c.calls),2)
    def test_calibration_files_not_modified(self):
        d=self.root/'config';d.mkdir();p=d/'face_commission.json';p.write_text('{"saved_neutral":1270}',encoding='utf-8');before=p.read_bytes()
        self.engine().recover(True,True,True);self.assertEqual(p.read_bytes(),before)
    def test_stale_status_ignored_and_fresh_paused_fault_blocked(self):
        now=time.time()
        for pid,mode,age in ((1,'running',100),(2,'paused',.1),(3,'fault',.1),(4,'idle',.1)):
            (self.root/'build'/('head_runtime_%d.json'%pid)).write_text(json.dumps(dict(owner_pid=pid,mode=mode,updated_epoch=now-age)),encoding='utf-8')
        self.assertEqual({r['pid'] for r in app.live_controllers(self.root,now)},{2,3})
    def test_gui_opens_idle_without_subprocess_or_checks_selected(self):
        import tkinter as tk
        w=tk.Tk();w.withdraw()
        try:
            with patch.object(app,'run_command') as runner:
                panel=app.RestartPanel(w);w.update_idletasks();self.assertFalse(panel.busy);self.assertFalse(panel.off.get());self.assertIsNone(panel.last_result);runner.assert_not_called()
                panel.start(False);self.assertFalse(panel.busy);runner.assert_not_called()
        finally:w.destroy()
class TclReadbackTests(unittest.TestCase):
    def test_actual_decimal_readback_and_active_board_guard(self):
        script='''rename exit native_exit
proc exit {code} {error "TEST_EXIT_$code"}
foreach name {connect configparams targets stop con rrd disconnect mrd} {
    if {[llength [info commands $name]]} {rename $name original_$name}
}
proc connect {} {}
proc configparams {args} {}
proc targets {args} {}
proc stop {} {incr ::stops}
proc con {} {incr ::resumes}
proc rrd {args} {return "mock PC"}
proc disconnect {} {}
proc mrd {args} {
    switch -- [lindex $args 1] {
        0x40000000 {return 842156110}
        0x40000004 {return 196630}
        0x4000000c {return $::active}
        default {return 0}
    }
}
foreach active {0 1} {
    set stops 0;set resumes 0
    catch {source {%s}} message
    if {$active == 0} {
        if {$message ne "TEST_EXIT_0" || $stops != 1 || $resumes != 1} {error "Decimal readback failed: $message"}
    } else {
        if {$message ne "TEST_EXIT_1" || $stops != 0 || $resumes != 0} {error "Active guard failed: $message"}
    }
}
puts "DECIMAL_READBACK_AND_ACTIVE_GUARD_PASS"
native_exit 0
''' % str(ROOT/'scripts/recover_cold_network.tcl').replace('\\','/')
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'tcl_readback_test.tcl';path.write_text(script,encoding='utf-8')
            result=subprocess.run([str(app.XSCT),str(path)],capture_output=True,timeout=20)
            self.assertEqual(result.returncode,0,result.stderr);self.assertIn(b'DECIMAL_READBACK_AND_ACTIVE_GUARD_PASS',result.stdout)

class AssetTests(unittest.TestCase):
    def test_recovery_asset_validation_allows_calibration_changes_but_rejects_image_tamper(self):
        with tempfile.TemporaryDirectory() as directory:
            r=Path(directory);(r/'scripts').mkdir();(r/'build').mkdir();(r/'config').mkdir()
            shutil.copy2(ROOT/'scripts/load_22.ps1',r/'scripts/load_22.ps1');shutil.copy2(ROOT/'build/release_manifest.json',r/'build/release_manifest.json')
            for name in ('build/firmware/nh22_udp.bin','build/reports/zynq_neurohead/neurohead_zynq.bit','build/reports/zynq_neurohead/ps7_init.tcl','scripts/load_monitor_jtag.tcl'):
                dest=r/name;dest.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(ROOT/name,dest)
            (r/'config/face_commission.json').write_text('{"operator_changed_neutral":1430}',encoding='utf-8')
            args=[app.powershell_path(),'-NoProfile','-File',str(r/'scripts/load_22.ps1'),'-ServoPowerOff','-SignalsDisconnected','-RecoveryAssetsOnly','-ValidateOnly']
            result=subprocess.run(args,capture_output=True,timeout=20);self.assertEqual(result.returncode,0,result.stderr);self.assertIn(b'PROGRAM_ASSETS_VERIFIED_NO_JTAG',result.stdout)
            image=r/'build/firmware/nh22_udp.bin';image.write_bytes(image.read_bytes()+b'corrupt')
            result=subprocess.run(args,capture_output=True,timeout=20);self.assertNotEqual(result.returncode,0);self.assertNotIn(b'MONITOR_BINARY_JTAG_LAUNCHED',result.stdout)
if __name__=='__main__':unittest.main(verbosity=2)
