import json,sys,tempfile,tkinter as tk,unittest
from pathlib import Path
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'src/pc'))
import neck_control_panel as ui
class Tests(unittest.TestCase):
    def test_mapping_hot_reload_changes_only_future_commands_and_not_active_status(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);(root/'config').mkdir();(root/'build').mkdir()
            path=root/'config/neck_follow.json'
            p=dict(yaw_reference_operator_verified=True,pair_first_output_no_abnormal_operator_confirmed=True,
                rod_directions_operator_verified=False)
            path.write_text(json.dumps(p));active=root/'build/neck_manual_active.json'
            active.write_text(json.dumps(dict(owner_pid=123,mode='running')))
            window=tk.Tk();window.withdraw();window.after=lambda *args:None
            try:
                with patch.object(ui,'ROOT',root):
                    panel=ui.Panel(window,controller_factory=ui.NeckControl);window.update()
                    self.assertTrue(all(str(b.cget('state'))=='disabled' for b in panel.mapping_buttons))
                    panel.preset([1550,1520,1480]);before=list(panel.control.desired)
                    p.update(rod_directions_operator_verified=True,rod_up_pwm_signs=[-1,1])
                    path.write_text(json.dumps(p));panel.refresh_mapping();window.update()
                    self.assertEqual(panel.control.desired,before);self.assertIsNone(panel.control.client)
                    self.assertTrue(all(str(b.cget('state'))=='normal' for b in panel.mapping_buttons))
                    panel.physical_preset(1,-1);self.assertEqual(panel.control.desired,[1550,1100,1100])
                    panel.physical_preset(-1,1);self.assertEqual(panel.control.desired,[1550,1900,1900])
                    panel.preset([1500]*3);panel.shift(50);self.assertEqual(panel.control.desired,[1500,1450,1550])
                    panel.poll()
                    self.assertEqual(json.loads(active.read_text())['owner_pid'],123)
                    self.assertIsNone(panel.control.client)
            finally:window.destroy()
    def test_neutral_hot_reload_and_recording_do_not_move_paused_pose(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);(root/'config').mkdir();(root/'build').mkdir()
            path=root/'config/neck_follow.json'
            p=dict(yaw_reference_operator_verified=True,pair_first_output_no_abnormal_operator_confirmed=True,
                rod_directions_operator_verified=True,rod_up_pwm_signs=[-1,1])
            path.write_text(json.dumps(p));window=tk.Tk();window.withdraw();window.after=lambda *args:None
            try:
                with patch.object(ui,'ROOT',root):
                    panel=ui.Panel(window,controller_factory=ui.NeckControl);window.update();panel.preset([1550,1520,1480])
                    p['manual_neck_reference_us']=[1500,1270,1500];path.write_text(json.dumps(p))
                    panel.refresh_mapping();self.assertEqual(panel.control.desired,[1550,1520,1480])
                    panel.home();self.assertEqual(panel.values(),[1500,1270,1500])
                    panel.physical_preset(1,-1);self.assertEqual(panel.control.desired,[1500,1100,1330])
                    panel.control.mode='running';panel.control.output=[1510,1263,1497]
                    panel.control.last_state={'status':1,'active_mask':7<<18}
                    panel.save_reference()
                    self.assertEqual(panel.control.mode,'paused')
                    self.assertEqual(json.loads(path.read_text())['manual_neck_reference_us'],[1510,1263,1497])
                    self.assertEqual(panel.control.output,[1510,1263,1497]);panel.home()
                    self.assertEqual(panel.values(),[1510,1263,1497]);self.assertIsNone(panel.control.client)
            finally:window.destroy()
    def test_logical_center_and_view_switch_preserve_physical_target(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);(root/'config').mkdir();(root/'build').mkdir()
            p=dict(yaw_reference_operator_verified=True,pair_first_output_no_abnormal_operator_confirmed=True,
                rod_directions_operator_verified=True,rod_up_pwm_signs=[-1,1],manual_neck_reference_us=[1500,1270,1500])
            (root/'config/neck_follow.json').write_text(json.dumps(p))
            window=tk.Tk();window.withdraw();window.after=lambda *args:None
            try:
                with patch.object(ui,'ROOT',root):
                    panel=ui.Panel(window,controller_factory=ui.NeckControl);window.update()
                    self.assertEqual([int(s.get()) for s in panel.scales],[1500]*3)
                    self.assertEqual(panel.values(),[1500,1270,1500])
                    panel.preset([1500,1585,1500]);self.assertEqual(panel.scales[1].get(),1700)
                    before=list(panel.control.desired)
                    panel.position_mode.set('physical');panel.switch_mode()
                    self.assertEqual(panel.scales[1].get(),1585);self.assertEqual(panel.control.desired,before)
                    panel.position_mode.set('logical');panel.switch_mode()
                    self.assertEqual(panel.scales[1].get(),1700);self.assertEqual(panel.control.desired,before)
                    panel.home();self.assertEqual([int(s.get()) for s in panel.scales],[1500]*3)
                    self.assertEqual(panel.control.desired,[1500,1270,1500]);self.assertIsNone(panel.control.client)
            finally:window.destroy()
    def test_side_amplitude_hot_save_changes_next_pose_only(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);(root/'config').mkdir();(root/'build').mkdir()
            p=dict(yaw_reference_operator_verified=True,pair_first_output_no_abnormal_operator_confirmed=True,
                rod_directions_operator_verified=True,rod_up_pwm_signs=[-1,1],manual_neck_reference_us=[1500,1270,1500])
            path=root/'config/neck_follow.json';path.write_text(json.dumps(p))
            window=tk.Tk();window.withdraw();window.after=lambda *args:None
            try:
                with patch.object(ui,'ROOT',root):
                    panel=ui.Panel(window,controller_factory=ui.NeckControl);window.update()
                    self.assertEqual(panel.side_spans,dict(left_up_right_down=170,left_down_right_up=170))
                    panel.preset([1500,1270,1500]);before=list(panel.control.desired)
                    panel.side_span_vars['left_down_right_up'].set('140');panel.save_side_spans()
                    self.assertEqual(panel.control.desired,before)
                    panel.physical_preset(-1,1);self.assertEqual(panel.control.desired,[1500,1410,1640])
                    panel.side_span_vars['left_down_right_up'].set('400');panel.save_side_spans()
                    self.assertEqual(json.loads(path.read_text())['side_preset_spans_us']['left_down_right_up'],140)
                    self.assertIsNone(panel.control.client)
            finally:window.destroy()
if __name__=='__main__':unittest.main(verbosity=2)