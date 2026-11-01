import hashlib,json,subprocess,sys,unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'src/pc'))
import board_restart as app
class MigrationTests(unittest.TestCase):
 def test_file_validation_does_not_require_physical_readiness(self):
  p=subprocess.run([app.powershell_path(),'-NoProfile','-File',str(ROOT/'scripts/load_22.ps1'),'-RecoveryAssetsOnly','-ValidateOnly'],capture_output=True,timeout=30)
  self.assertEqual(p.returncode,0,p.stderr);self.assertIn(b'PROGRAM_ASSETS_VERIFIED_NO_JTAG',p.stdout)
 def test_programming_still_refuses_without_both_readiness_flags(self):
  p=subprocess.run([app.powershell_path(),'-NoProfile','-File',str(ROOT/'scripts/load_22.ps1'),'-RecoveryAssetsOnly'],capture_output=True,timeout=30)
  self.assertNotEqual(p.returncode,0);self.assertIn(b'Before JTAG',p.stderr);self.assertNotIn(b'MONITOR_BINARY_JTAG_LAUNCHED',p.stdout)
 def test_debugger2026_has_required_tcl_commands_without_connecting(self):
  p=subprocess.run([str(app.XSCT),str(ROOT/'scripts/probe_debugger2026.tcl')],capture_output=True,timeout=30)
  self.assertEqual(p.returncode,0,p.stderr);self.assertIn(b'XSDB2026_RECOVERY_COMMANDS_AVAILABLE',p.stdout)
 def test_generated_ps_init_matches_verified_platform_and_new_bit_is_pinned(self):
  report=json.loads((ROOT/'build/migration/migration_status.json').read_text(encoding='utf-8'))
  self.assertEqual(report['ps_init_sha256'],'16895e9ca2d108224318b3cbf5453c77fdeb0e4c22fb01c2e1b745d3c4200f77')
  self.assertEqual(hashlib.sha256((ROOT/'build/reports/zynq_neurohead/neurohead_zynq.bit').read_bytes()).hexdigest(),report['bit_sha256'])
  self.assertIn(report['bit_sha256'],(ROOT/'scripts/load_22.ps1').read_text(encoding='utf-8'))
if __name__=='__main__':unittest.main()
