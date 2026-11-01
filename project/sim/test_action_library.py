"""Registered action scheduling and actual packet envelopes; fake board only."""
import copy,json,math,struct,unittest
from pathlib import Path
from unittest.mock import patch
import test_left_lower_lid_guard as guard
from action_library import HeadGesture,validate_actions
from head_control import MASK,CHANNELS
from head_motion import MotionBank
from expression_presets import wink_signature


class TrajectoryTests(unittest.TestCase):
    def test_all_head_trajectories_return_and_respect_rate_and_reference(self):
        from test_head_control import profile
        p=profile();p['neck_tracking_rate_us_per_s']=[50,35]
        for name in ('head_up','eyes_up','shake_head'):
            for base in ([1500,1500,1500,1270,1500],[1550,1510,1595,1175,1595]):
                if name=='head_up' and base[3]==1175:
                    with self.assertRaisesRegex(ValueError,'上边界'):HeadGesture(name,list(base),p,0)
                    continue
                g=HeadGesture(name,list(base),p,0)
                last=g.sample(0)
                for tick in range(1,math.ceil(g.end/.05)+2):
                    out=g.sample(tick*.05)
                    for index,u in out.items():
                        self.assertLessEqual(abs(u-last[index]),g.rates[index]*.05+1.01)
                        self.assertTrue(g.limits[index][0]<=u<=g.limits[index][1])
                    last=out
                self.assertEqual(last,{i:base[i] for i in g.indices})
        gesture=HeadGesture('head_up',[1500,1500,1500,1270,1500],p,0)
        self.assertEqual(gesture.sample(gesture.segments[0][1]+.1),{3:1170,4:1600})

    def test_cancel_returns_from_current_without_jump(self):
        from test_head_control import profile
        base=[1500,1500,1500,1270,1500];g=HeadGesture('shake_head',base,profile(),0)
        current=list(base)
        for i,u in g.sample(1).items():current[i]=u
        g.cancel(1,current)
        self.assertEqual(g.sample(1),{2:current[2]});self.assertEqual(g.sample(g.end),{2:1500})

    def test_only_registered_names_no_custom_parameters(self):
        for value in (None,'head_up',['raw_pwm'],['head_up']*4,[{'name':'head_up','us':1900}],['wink','wink']):
            with self.assertRaises(ValueError):validate_actions(value)
        self.assertEqual(validate_actions(['head_up','smile']),['head_up','smile'])


class SchedulerTests(unittest.TestCase):
    make=guard.GuardTests.make

    def start_actions(self,c,names,request='first'):
        c.profile['neck_tracking_rate_us_per_s']=[50,35]
        c.set_action_library(True,True)
        return c.life_event(dict(type='action',request_id=request,actions=names))

    def step(self,c,count=1):
        for _ in range(count):self.clock[0]+=.05;c.tick(.05)

    def test_default_off_cannot_be_enabled_by_llm_or_custom_parameters(self):
        c=self.make();self.addCleanup(c.end,True)
        with self.assertRaises(ValueError):c.set_action_library(True,False)
        with self.assertRaises(ValueError):c.life_event(dict(type='action',request_id='x',actions=['head_up']))
        c.set_action_library(True,True)
        with self.assertRaises(ValueError):c.life_event(dict(type='action',request_id='x',actions=['head_up'],us=1900))
        with self.assertRaises(ValueError):c.life_event(dict(type='action',request_id='x',actions=['smile']))
        with self.assertRaises(ValueError):c.life_event(dict(type='action',request_id='x',actions=['unknown']))
        self.assertFalse(c.action_queue)

    def test_head_and_face_sequence_completes_and_inhibited_lid_never_emits(self):
        c=self.make();self.addCleanup(c.end,True);c.enable_life(True)
        self.step(c,15)
        self.start_actions(c,['head_up','smile','shake_head'])
        names=set();outputs=[]
        for _ in range(750):
            self.step(c)
            if c.active_action:names.add(c.active_action['name'])
            out=c.last_state['output_us'];outputs.append(out)
            mask=c.last_state['active_mask'];self.assertFalse(mask&(1<<7));self.assertEqual(mask&MASK,MASK)
            for ch,r in zip((18,19,20),(1500,1270,1500)):self.assertTrue(r-100<=out[ch]<=r+100)
        self.assertEqual(names,{'head_up','smile','shake_head'})
        self.assertIsNone(c.active_action);self.assertFalse(c.action_queue)
        self.assertEqual(c.action_last['status'],'completed')
        self.assertEqual(c.output,list(c.reference))
        self.assertLess(min(v[19] for v in outputs),1250)
        self.assertLess(min(v[18] for v in outputs),1480);self.assertGreater(max(v[18] for v in outputs),1520)

    def test_cancel_dedup_busy_and_old_request_cannot_cancel_new(self):
        c=self.make();self.addCleanup(c.end,True)
        self.start_actions(c,['shake_head']);self.step(c,12)
        same=c.life_event(dict(type='action',request_id='first',actions=['shake_head']))
        self.assertTrue(same['duplicate'])
        with self.assertRaises(ValueError):c.life_event(dict(type='action',request_id='other',actions=['head_up']))
        c.life_event(dict(type='action.cancel',request_id='first'));self.step(c,160)
        self.assertEqual(c.action_last['status'],'cancelled');self.assertEqual(c.output,list(c.reference))
        c.life_event(dict(type='action',request_id='new',actions=['eyes_up']));self.step(c,5)
        self.assertFalse(c.life_event(dict(type='action.cancel',request_id='first')))
        self.assertEqual(c.active_action['request_id'],'new')
        c.pause();self.assertIsNone(c.active_action);self.assertFalse(c.action_queue);self.assertFalse(c.action_enabled)

    def test_actions_finish_without_changing_coordinated_tracking(self):
        from test_head_control import row
        c=self.make();self.addCleanup(c.end,True)
        c.tracking='coordinated';c.motion_style='natural'
        fresh=row(target=[0,0]);c.vision=lambda:fresh
        c.last_good_record={}
        self.start_actions(c,['head_up','eyes_up'])
        # A real profile has a passed direction record; replace only its rebuilding IO.
        def restore(core,kind):core.tracking=kind
        with patch('head_control.HeadControl._visual_tick') as visual,patch('head_control.HeadControl.set_follow',restore):
            self.step(c,500)
            self.assertGreater(visual.call_count,200)
        self.assertEqual(c.tracking,'coordinated');self.assertEqual(c.action_last['status'],'completed')

    def test_visual_hold_aborts_gesture_and_queue_at_current_output(self):
        c=self.make();self.addCleanup(c.end,True)
        c.tracking='eyes'
        self.start_actions(c,['shake_head','head_up'])
        with patch('head_control.HeadControl._visual_tick'):
            self.step(c,12)
        held=list(c.output)
        c.vision=lambda:None;self.step(c)
        self.assertEqual(c.tracking,'manual');self.assertIsNone(c.active_action);self.assertFalse(c.action_queue)
        self.assertEqual(c.output,held);self.assertEqual(c.action_last['reason'],'visual_hold')

    def test_wink_still_requires_direction_approval_and_dispatch_does_not_enable_face(self):
        c=self.make();self.addCleanup(c.end,True);c.enable_life(True);self.step(c,15)
        c.set_action_library(True,True)
        c.engine.config['wink_right_approval']={'verified':False}
        with self.assertRaisesRegex(ValueError,'确认'):c.life_event(dict(type='action',request_id='x',actions=['wink']))
        c.engine.config['wink_right_approval']={'verified':True,'tracking_clear':True,'pose':wink_signature(c.engine.poses[8])}
        self.start_actions(c,['wink']);self.step(c,35)
        self.assertEqual(c.action_last['status'],'completed');self.assertFalse(c.engine.config['automatic_blink'])

    def test_disable_library_returns_and_clears_future_actions(self):
        c=self.make();self.addCleanup(c.end,True)
        self.start_actions(c,['head_up','shake_head']);self.step(c,20)
        c.set_action_library(False);self.step(c,160)
        self.assertEqual(c.output,list(c.reference));self.assertIsNone(c.active_action);self.assertFalse(c.action_queue)


if __name__=='__main__':unittest.main()
