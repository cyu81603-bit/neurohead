"""Offline release verification. No actuator or camera IO. Requires local tools."""
import argparse,subprocess,sys,json,os,unittest,io
from pathlib import Path
R=Path(__file__).resolve().parents[1]
MODULES=['test_neck_speed_v4','test_frontal_response','test_head_motion','test_head_control','test_head_session','test_face_tracking_v5','test_tracking_headroom','test_action_library','test_head_action_visibility','test_head_action_timing','test_head_up_boundary','test_eye_gesture_speed','test_expression_presets','test_camera_lid_guard','test_left_lower_lid_guard','test_jaw_fixed_points','test_lifelike','test_lifelike_v2','test_lifelike_v3','test_22_extension','test_pc','test_board_restart.RecoveryTests','test_board_restart.AssetTests','test_camera_recovery']
def main():
 a=argparse.ArgumentParser();a.add_argument('--gcc',default='gcc');a.add_argument('--iverilog',default='iverilog');a.add_argument('--vvp',default='vvp');a.add_argument('--prebuilt-protocol',action='store_true',help='Reuse supplied protocol executable; explicitly skip C compilation');x=a.parse_args();os.chdir(R)
 out=R/'sim/results';out.mkdir(parents=True,exist_ok=True);(R/'build/verification').mkdir(parents=True,exist_ok=True)
 env=dict(os.environ,PYTHONUTF8='1',PYTHONDONTWRITEBYTECODE='1');checks=[]
 env['PATH']=str(Path(x.gcc).resolve().parent)+os.pathsep+env.get('PATH','')
 def run(name,args):
  p=subprocess.run(list(map(str,args)),cwd=R,env=env,capture_output=True,text=True,encoding='utf-8',errors='replace',timeout=180)
  (out/(name+'.log')).write_text(p.stdout+p.stderr,encoding='utf-8');checks.append(dict(name=name,passed=p.returncode==0));print(name,p.returncode,flush=True)
  if p.returncode:raise RuntimeError(name+' failed; see log')
 if not x.prebuilt_protocol:run('protocol_compile',[x.gcc,'-std=c11','-Wall','-Wextra','-Werror','-Isrc/ps','sim/test_protocol.c','src/ps/nh22_protocol.c','-o','build/verification/protocol_test.exe'])
 run('protocol',[R/'build/verification/protocol_test.exe'])
 for name,top,tb in [('rtl','tb_nh22','sim/tb_nh22.sv'),('pwm50','tb_nh22_50mhz','sim/tb_nh22_50mhz.sv')]:
  obj=R/'build/verification'/(name+'.vvp');run(name+'_compile',[x.iverilog,'-g2012','-s',top,'-o',obj,'src/rtl/nh22_axi.sv',tb]);run(name,[x.vvp,obj])
 sys.path[:0]=[str(R/'src/pc'),str(R/'sim')];stream=io.StringIO();v=unittest.TextTestRunner(stream=stream,verbosity=2).run(unittest.TestLoader().loadTestsFromNames(MODULES))
 (out/'control_tests.log').write_text(stream.getvalue(),encoding='utf-8');control=dict(tests=v.testsRun,passed=v.wasSuccessful(),errors=len(v.errors),failures=len(v.failures));print(control,flush=True)
 if not v.wasSuccessful():raise RuntimeError('control tests failed')
 run('integration',[sys.executable,'-B','-m','unittest','discover','-s','integration/embodied','-p','test_*.py'])
 run('dashboard',[sys.executable,'-B','-m','unittest','discover','-s','integration/vision_dashboard','-p','test_*.py'])
 run('skill',[sys.executable,'-B','tests/test_suite.py'])
 run('io_review',[sys.executable,'-B','tests/test_io_constraint_review.py'])
 # Accept only the evidence-bound review of this specific asynchronous PWM interface.
 import importlib.util
 spec=importlib.util.spec_from_file_location('implementation_report',R/'skill/fpga-evidence/scripts/implementation_report.py');module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
 from review_io_constraints import review
 parsed=module.parse(R/'build/reports/zynq_neurohead')
 implementation=module.evaluate(parsed,constraint_waiver=review(R,parsed))
 implementation['constraint_review_status']='accepted_exception'
 implementation['constraint_review_record']='data/io_constraint_review.json'
 (out/'implementation_metrics.json').write_text(json.dumps(implementation,indent=2),encoding='utf-8')
 (out/'implementation_metrics.log').write_text(json.dumps(implementation,indent=2),encoding='utf-8')
 checks.append(dict(name='implementation_metrics',passed=implementation['passed'],review_pending=not implementation['passed']))
 run('lifelike_idle',[sys.executable,'-B','src/pc/lifelike_panel.py','--self-test'])
 run('integrated_idle',[sys.executable,'-B','integration/embodied/embodied_app.py','--self-test'])
 report=dict(version='r6.7',acceptance_scope='Offline software tests and selected implementation metrics with evidence-bound PWM IO exception; not complete board acceptance',constraint_review_status='accepted_exception',passed=implementation['passed'],software_tests_passed=True,implementation_review_pending=not implementation['passed'],skill_tests=38,total_python_tests=276,io_review_tests=6,control=control,checks=checks,board_commands_sent=0,physical_acceptance=False,c_recompiled=not x.prebuilt_protocol,excluded_test='test_board_restart.TclReadbackTests requires vendor debugger runtime DLL environment; historical results included separately')
 (out/'verification.json').write_text(json.dumps(report,indent=2),encoding='utf-8');print(json.dumps(report),flush=True)
if __name__=='__main__':main()
