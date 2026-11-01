import copy,math,sys,time,unittest
from pathlib import Path
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'src/pc'));sys.path.insert(0,str(ROOT/'sim'))
from head_control import HeadControl,MASK,CHANNELS
from head_coordination import Coordinator,identification_plan,analyze_identification,neck_pose,validate_direction_record,camera_setup_signature
from test_vertical_feedback import EyeClient

def profile():return dict(yaw_reference_operator_verified=True,pair_first_output_no_abnormal_operator_confirmed=True,
    manual_neck_reference_us=[1500,1270,1500],rod_up_pwm_signs=[-1,1],rod_directions_operator_verified=True,
    operator_ready_this_session=True,neck_position_control_operator_confirmed=True,camera_mount='moves_with_eyeball',eye_vertical_limits_us=[1000,2000])
def row(frame=1,target=None,sid='cam'):
    stamp=time.monotonic()
    return dict(host_monotonic_s=stamp,vision=dict(camera_index='USB Cam',detector='yunet_2023mar',running=True,error=None,
        source_session_id=sid,frame_id=frame,frame_time=stamp,target=target))
class Lock:
    def close(self):pass
class Client(EyeClient):
    fail=False
    def exchange(self,p):
        if self.fail and p[:2]==b'NH':self.packets.append(p);raise RuntimeError('link failure')
        return super().exchange(p)
class CoreTests(unittest.TestCase):
    def core(self):
        Client.instances=[];Client.fail=False;self.frame=row(target=[.3,.2])
        c=HeadControl(profile(),vision=lambda:self.frame,client_factory=Client,lock_factory=lambda _:Lock())
        c._guard=lambda:None
        return c
    def start(self,c):
        with patch('eye_follow_panel.verified_command',return_value=[]):c.start()
    def test_idle_and_current_readiness_gate(self):
        c=self.core();c.tick(.05);self.assertFalse(Client.instances)
        c.profile['operator_ready_this_session']=False
        with self.assertRaises(ValueError):self.start(c)
        self.assertFalse(Client.instances)
    def test_all_five_mask_config_holding_and_neutral(self):
        c=self.core();self.start(c);c.tick(.05)
        self.assertEqual(c.output,[1500,1500,1500,1270,1500])
        client=Client.instances[-1];configs=[p for p in client.packets if p[:2]==b'NC']
        self.assertEqual([p[8] for p in configs],[0,1,18,19,20]);self.assertEqual([p[9] for p in configs],[0,0,1,1,1])
        self.assertEqual([int.from_bytes(p[16:18],'little') for p in configs],[4,2,2,2,2])
        for packet in (p for p in client.packets if p[:2]==b'NH'):
            self.assertEqual(int.from_bytes(packet[8:12],'little'),MASK)
            import struct
            values=struct.unpack_from('<22H',packet,12)
            self.assertTrue(all(values[k]==0 for k in range(2,18)))
        with self.assertRaises(ValueError):c.end()
        c.end(True);self.assertEqual(c.mode,'idle')
    def test_eye_tracking_preserves_manual_neck_goal(self):
        c=self.core();self.start(c);self.frame['vision']['frame_time']-=.1;c.set_follow('eyes')
        c.set_targets([1500,1500,1700,1300,1570]);c.tick(.05)
        self.assertEqual(c.desired[2:],[1700,1300,1570])
        self.frame=row(2,[.4,.1]);c.tick(.05);self.assertLess(c.desired[0],1500)
        self.assertEqual(c.desired[2:],[1700,1300,1570]);c.end(True)
    def test_stale_or_restarted_camera_holds_without_global_stop(self):
        c=self.core();self.start(c);c.set_follow('eyes');c.tick(.05)
        self.frame=row(2,[.2,.2],sid='new-cam');c.tick(.05)
        self.assertEqual(c.tracking,'manual');self.assertEqual(c.desired,c.output)
        self.assertFalse(any(p[:2]==b'NS' for p in Client.instances[-1].packets))
        # Only an explicit new follow request adopts a restarted camera.
        c.set_follow('eyes');self.assertEqual(c.camera_session,'new-cam')
        self.frame['host_monotonic_s']-=2;c.tick(.05);self.assertEqual(c.tracking,'manual');c.end(True)
    def test_fault_preserves_hold_policy_and_pause(self):
        c=self.core();self.start(c);c.tick(.05);c.pause();held=list(c.output)
        c.tick(.05);self.assertEqual(c.output,held)
        Client.fail=True;c.tick(.05);self.assertEqual(c.mode,'fault')
        self.assertFalse(any(p[:2]==b'NS' for p in Client.instances[-1].packets))
        Client.fail=False;c.end(True)
    def test_successful_direction_survives_failed_repeat_and_requires_explicit_follow(self):
        c=self.core();self.start(c)
        phases=identification_plan(profile())
        obs={i:{k:[.001*p['yaw'],.002*p['pitch']] for k in range(8)} for i,p in enumerate(phases)}
        cal=analyze_identification(phases,obs,[1500,1270,1500])
        c.last_good_record=dict(success=True,calibration=cal,camera_session='cam',completed_epoch=1.)
        c.set_follow('coordinated');self.assertEqual(c.tracking,'coordinated')
        c.begin_identification();self.frame['host_monotonic_s']-=2;c.tick(.05)
        self.assertEqual(c.tracking,'manual');self.assertFalse(c.ident_result['success'])
        self.assertTrue(c.last_good_record['success']);self.assertIsNotNone(c.calibration)
        self.frame=row(2,[.2,.2]);c.set_follow('coordinated');self.assertEqual(c.tracking,'coordinated');c.end(True)
    def test_natural_style_output_uses_small_vertical_steps_and_switch_keeps_pose(self):
        c=self.core();self.start(c);c.set_motion_style('natural')
        self.frame=row(target=[.3,.4]);c._fresh_vision=lambda:self.frame
        c.set_follow('eyes');values=[]
        for i in range(120):
            self.frame['vision'].update(frame_id=i//3,frame_time=(i//3)*.06)
            c.tick(.02);values.append(c.output[1])
        self.assertTrue(any(v%10 for v in values));self.assertGreater(max(values)-min(values),20)
        self.assertLessEqual(max(abs(a-b) for a,b in zip(values,values[1:])),3)
        before=list(c.output);c.set_motion_style('legacy');self.assertEqual(c.output,before)
        self.assertEqual(c.tracking,'eyes');self.assertFalse(any(p[:2]==b'NS' for p in Client.instances[-1].packets));c.end(True)
    def test_coordination_requires_response_and_valid_targets(self):
        c=self.core();self.start(c)
        with self.assertRaises(ValueError):c.set_follow('coordinated')
        with self.assertRaises(ValueError):c.set_targets([1500,1500,1500,1000,1500])
        c.end(True)
class MathTests(unittest.TestCase):
    def observations(self,phases,J):
        return {i:{i*10+k:[.03+J[0][0]*p['yaw']+J[0][1]*p['pitch'],.02+J[1][0]*p['yaw']+J[1][1]*p['pitch']] for k in range(8)} for i,p in enumerate(phases)}
    def test_identifies_both_signs_and_cross_coupling(self):
        p=profile();phases=identification_plan(p);J=[[-.001,.0002],[.0001,.002]]
        c=analyze_identification(phases,self.observations(phases,J),[1500,1270,1500])
        self.assertTrue(c['valid'])
        for i in (0,1):
            for j in (0,1):self.assertAlmostEqual(c['jacobian'][i][j],J[i][j])
        self.assertEqual(phases[-1]['target'],[1500,1500,1500,1270,1500])
    def test_identification_rejects_drift_missing_and_rank_loss(self):
        phases=identification_plan(profile());obs=self.observations(phases,[[.001,.001],[.002,.002]])
        with self.assertRaises(ValueError):analyze_identification(phases,obs,[1500,1270,1500])
        obs=self.observations(phases,[[.001,0],[0,.002]]);obs[0]={}
        with self.assertRaises(ValueError):analyze_identification(phases,obs,[1500,1270,1500])
        obs=self.observations(phases,[[.001,0],[0,.002]]);obs[8]={i:[.3,.3] for i in range(8)}
        with self.assertRaises(ValueError):analyze_identification(phases,obs,[1500,1270,1500])
    def test_pose_envelope_reference_and_direction(self):
        self.assertEqual(neck_pose(profile(),0,100),[1500,1170,1600])
        with self.assertRaises(ValueError):neck_pose(profile(),0,171)
    def test_local_direction_identification_keeps_drift_warning(self):
        phases=identification_plan(profile());obs=self.observations(phases,[[.002,0],[0,.005]])
        # Linear target/reference drift cancels in each bracketed local step;
        # it must remain visible and must not be called repeatable calibration.
        for index,frames in obs.items():
            for value in frames.values():value[0]+=.025*index
        with self.assertRaises(ValueError):analyze_identification(phases,obs,[1500,1270,1500])
        cal=analyze_identification(phases,obs,[1500,1270,1500],allow_reference_drift=True)
        self.assertTrue(cal['provisional_direction_only']);self.assertFalse(cal['reference_repeatable'])
        self.assertAlmostEqual(cal['jacobian'][0][0],.002)
        for frames in obs.values():
            for value in frames.values():value[0]*=4
        with self.assertRaises(ValueError):analyze_identification(phases,obs,[1500,1270,1500],allow_reference_drift=True)
    def test_saved_direction_rejects_camera_reference_or_inverse_changes(self):
        p=profile();phases=identification_plan(p)
        cal=analyze_identification(phases,self.observations(phases,[[.001,0],[0,.002]]),[1500,1270,1500])
        record=dict(success=True,calibration=cal,camera_session='same')
        accepted=validate_direction_record(record,p,'same');self.assertEqual(accepted['automatic_yaw_limit_us'],100)
        with self.assertRaises(ValueError):validate_direction_record(record,p,'different')
        changed=copy.deepcopy(record);changed['calibration']['reference_us'][1]=1500
        with self.assertRaises(ValueError):validate_direction_record(changed,p,'same')
        changed=copy.deepcopy(record);changed['calibration']['inverse'][0][0]*=2
        with self.assertRaises(ValueError):validate_direction_record(changed,p,'same')
    def test_preview_restart_reuses_only_confirmed_unchanged_setup(self):
        p=profile();cam=dict(device_name='USB Cam',device_path='device',width=640,height=480,fps=30,fallback_to_builtin=False)
        sig=camera_setup_signature(p,cam);p.update(camera_setup_signature=sig,camera_setup_operator_confirmed=True)
        phases=identification_plan(p);cal=analyze_identification(phases,self.observations(phases,[[.001,0],[0,.002]]),[1500,1270,1500])
        record=dict(success=True,calibration=cal,camera_session='old',camera_setup_signature=sig)
        self.assertTrue(validate_direction_record(record,p,'new')['valid'])
        p['camera_setup_operator_confirmed']=False
        with self.assertRaises(ValueError):validate_direction_record(record,p,'new')
    def test_changed_camera_configuration_invalidates_old_direction_even_same_uuid(self):
        p=profile();cam=dict(device_name='USB Cam',device_path='device',width=640,height=480,fps=30)
        old=camera_setup_signature(p,cam);cam['width']=1280;new=camera_setup_signature(p,cam)
        self.assertNotEqual(old,new);p.update(camera_setup_signature=new,camera_setup_operator_confirmed=True)
        phases=identification_plan(p);cal=analyze_identification(phases,self.observations(phases,[[.001,0],[0,.002]]),[1500,1270,1500])
        with self.assertRaises(ValueError):validate_direction_record(dict(success=True,calibration=cal,camera_session='same',camera_setup_signature=old),p,'same')
    def test_first_coordination_trial_stays_inside_100us_offsets(self):
        c=Coordinator(profile(),[1200,1200,1500,1270,1500])
        cal=dict(valid=True,reference_us=[1500,1270,1500],inverse=[[1000,0],[0,1000]],
            automatic_yaw_limit_us=100,automatic_pitch_limit_us=100,
            automatic_yaw_rate_us_per_s=20,automatic_pitch_rate_us_per_s=15)
        values=[1200,1200,1500,1270,1500]
        for i in range(1,1001):
            out=c.update(dict(frame_id=i,frame_time=i*.05,target=[.5,.5]),values,cal)
            self.assertTrue(1400<=out[2]<=1600);self.assertTrue(1170<=out[3]<=1370);self.assertTrue(1400<=out[4]<=1600)
        self.assertEqual(out[2],1400);self.assertEqual(out[4],1400)
    def test_synthetic_eye_neck_loop_transfers_eye_offset(self):
        p=profile();c=Coordinator(p,[1500,1500,1500,1270,1500])
        cal=dict(valid=True,reference_us=[1500,1270,1500],inverse=[[1000,0],[0,1000]])
        values=[1500,1500,1500,1270,1500];early=None
        for i in range(1,1001):
            x=.4+.002*(values[0]-1500)+.001*(values[2]-1500)
            y=.12+.002*(values[1]-1500)+.001*(values[4]-1500)
            values=c.update(dict(frame_id=i,frame_time=i*.05,target=[x,y]),values,cal)
            if i==100:early=abs(values[0]-1500)
        self.assertLess(values[2],1400);self.assertLess(abs(values[0]-1500),early)
        self.assertLess(abs(x),.05);self.assertLess(abs(y),.05)
        before=list(values);self.assertIsNone(c.update(dict(frame_id=1000,frame_time=50.,target=[.8,.8]),values,cal))
        self.assertEqual(values,before)
if __name__=='__main__':unittest.main(verbosity=2)