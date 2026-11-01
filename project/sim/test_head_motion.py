import copy,json,math,sys,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'src/pc'));sys.path.insert(0,str(ROOT/'sim'))
from head_motion import MotionAxis,MotionBank,NaturalCoordinator,LatestFrameBuffer
from head_coordination import Coordinator
from test_head_control import profile,row

def simulate(style):
    p=profile();values=[1500,1500,1500,1270,1500];command=list(map(float,values));desired=list(values)
    control=(NaturalCoordinator if style=='natural' else Coordinator)(p,values)
    bank=MotionBank(values,[1000,2000],[1500,1270,1500])
    cal=dict(valid=True,reference_us=[1500,1270,1500],inverse=[[577,19],[-12,191]],
        automatic_yaw_limit_us=100,automatic_pitch_limit_us=100,automatic_yaw_rate_us_per_s=20,automatic_pitch_rate_us_per_s=15)
    samples=[];errors=[];v=None;frame=0;wire=list(values)
    for tick in range(3000):
        t=tick*.01
        # A moving face viewed by the eye-mounted camera, with mild box jitter.
        x=.28*math.sin(2*math.pi*.08*t)+.002*(values[0]-1500)+.00173*(values[2]-1500)
        y=.17*math.sin(2*math.pi*.065*t+.4)+.002*(values[1]-1500)+.00521*(values[4]-1500)
        if tick%7==0:
            frame+=1;noise=.006*math.sin(frame*2.1)
            v=dict(frame_id=frame,frame_time=t,target=[x+noise,y-noise])
        period=5
        if tick%period==0:
            target=control.update(v,values,cal)
            if target is not None:desired=target
            if style=='natural':command=bank.step(desired,.05,True);wire=[round(x) for x in command]
            else:
                command=[u+max(-r*.05,min(r*.05,target-u)) for u,target,r in zip(command,desired,[200,100,100,100,100])]
                wire=[round(x) for x in command];wire[1]=round(wire[1]/10)*10
        if tick%2==0:
            steps=[4,2,2,2,2] if style=='natural' else [10,10,2,2,2]
            values=[u+max(-step,min(step,target-u)) for u,target,step in zip(values,wire,steps)]
        samples.append(list(values));errors.append((x*x+y*y)/2)
    acceleration=[]
    for a,b,c in zip(samples,samples[1:],samples[2:]):
        acceleration.extend((c[i]-2*b[i]+a[i])/.0001 for i in (0,1))
    return dict(style=style,tracking_rms=math.sqrt(sum(errors[500:])/len(errors[500:])),
        eye_command_acceleration_rms=math.sqrt(sum(x*x for x in acceleration)/len(acceleration)),
        ranges=[[min(s[i] for s in samples),max(s[i] for s in samples)] for i in range(5)])

class MotionTests(unittest.TestCase):
    def test_velocity_acceleration_and_jerk_are_bounded_through_reversal(self):
        axis=MotionAxis(1500,1100,1900);old_a=0
        for i in range(500):
            axis.step(1700 if i<120 else 1300,.02,200,700,5000)
            self.assertLessEqual(abs(axis.velocity),200+1e-8);self.assertLessEqual(abs(axis.acceleration),700+1e-8)
            self.assertLessEqual(abs(axis.acceleration-old_a),100+1e-8);old_a=axis.acceleration
            self.assertTrue(1100<=axis.position<=1900)
    def test_slow_motion_accumulates_and_automatic_neck_envelope_is_retained(self):
        bank=MotionBank([1500,1500,1500,1270,1500],[1000,2000],[1500,1270,1500])
        for i in range(600):
            out=bank.step([1500+i*.04,1500,1800,1000,2000],.02,True)
            self.assertTrue(1400<=out[2]<=1600);self.assertTrue(1170<=out[3]<=1370);self.assertTrue(1400<=out[4]<=1600)
        self.assertGreater(out[0],1522)
    def test_frame_buffer_ignores_late_frames_and_short_read_failures(self):
        b=LatestFrameBuffer();a=row(10,[.1,.1]);self.assertTrue(b.accept(a))
        late=copy.deepcopy(a);late['vision']['frame_id']=9;late['vision']['frame_time']-=.06
        self.assertFalse(b.accept(late));self.assertFalse(b.accept(None));self.assertEqual(b.row['vision']['frame_id'],10)
        self.assertEqual(b.late_frames,1);self.assertEqual(b.read_errors,1)
        new=row(1,[.1,.1],sid='new');new['vision']['frame_time']=a['vision']['frame_time']+.1
        self.assertTrue(b.accept(new));self.assertEqual(b.row['vision']['source_session_id'],'new')
    def test_old_boot_timestamps_cannot_poison_fresh_camera_buffer(self):
        b=LatestFrameBuffer();old=row(9000,[.1,.1],sid='previous_boot')
        old['host_monotonic_s']=old['vision']['frame_time']=90000.
        self.assertFalse(b.accept(old,now=100.))
        new=row(1,[.1,.1],sid='current_boot')
        new['host_monotonic_s']=new['vision']['frame_time']=100.
        self.assertTrue(b.accept(new,now=100.05))
        self.assertEqual(b.row['vision']['source_session_id'],'current_boot')
        self.assertFalse(b.accept(old,now=100.1))
        self.assertEqual(b.row['vision']['source_session_id'],'current_boot')
    def test_fresh_restart_replaces_old_boot_high_water_without_accepting_stale_frames(self):
        b=LatestFrameBuffer();old=row(9000,[.1,.1],sid='previous_boot')
        old['host_monotonic_s']=old['vision']['frame_time']=90000.
        self.assertTrue(b.accept(old))
        new=row(1,[.1,.1],sid='current_boot')
        new['host_monotonic_s']=new['vision']['frame_time']=100.
        self.assertTrue(b.accept(new,now=100.05))
        stale=copy.deepcopy(new);stale['vision']['frame_id']=2
        self.assertFalse(b.accept(stale,now=101.))
        late=copy.deepcopy(new);late['vision']['frame_id']=0;late['vision']['frame_time']=99.99
        self.assertFalse(b.accept(late,now=100.1))
        self.assertEqual(b.row['vision']['frame_id'],1)
    def test_natural_hold_on_brief_face_loss_and_same_frame(self):
        p=profile();c=NaturalCoordinator(p,[1600,1600,1500,1270,1500]);values=[1600,1600,1500,1270,1500]
        for i in range(6):
            out=c.update(dict(frame_id=i,frame_time=i*.05,target=None),values)
            self.assertEqual(out[:2],[1600,1600])
        self.assertIsNone(c.update(dict(frame_id=5,frame_time=.25,target=[.4,.4]),values))
        for i in range(6,30):out=c.update(dict(frame_id=i,frame_time=i*.05,target=None),values)
        self.assertLess(out[0],1600)
    def test_log_tail_uses_open_handle_size_and_tolerates_partial_line(self):
        from vision_bridge import _latest_once
        with tempfile.TemporaryDirectory() as directory:
            p=Path(directory)/'v.jsonl';p.write_text('{"frame":1}\n{"frame":2}\n{"unfinished"',encoding='utf-8')
            with patch.object(Path,'stat',side_effect=AssertionError('path stat races rotation')):
                self.assertEqual(_latest_once(p),{'frame':2})
    def test_synthetic_closed_loop_is_smoother_without_large_tracking_loss(self):
        old=simulate('legacy');new=simulate('natural')
        self.assertLess(new['eye_command_acceleration_rms'],old['eye_command_acceleration_rms']*.85)
        self.assertLess(new['tracking_rms'],old['tracking_rms']*1.5+.01)
        print('SYNTHETIC_MOTION_COMPARISON '+json.dumps({'legacy':old,'natural':new}),flush=True)
if __name__=='__main__':unittest.main(verbosity=2)