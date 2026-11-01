import copy,sys,unittest
from pathlib import Path
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1];sys.path[:0]=[str(ROOT/'src/pc'),str(ROOT/'sim')]
from test_lifelike import config
from test_head_control import profile,Lock
from test_face_commission import Board
from lifelike_control import LifelikeControl
from lifelike_behavior import ExpressionEngine,approved_poses,pose_valid
from head_control import MASK

def probe_config():
 c=config()
 p=next(p for p in c['poses'] if p['channel']==21)
 p.update(neutral_us=1500,min_us=1475,max_us=1525,action_us=1525,max_rate_us_per_s=50,range_confirmed=False,enabled=False,action_verified=False,probe_only=True,neutral_verified=True,forbidden_pulses_us=[1100,1900])
 return c
class V2Tests(unittest.TestCase):
 def make(self,cfg):
  Board.instances=[];Board.fail=False;self.now=0
  c=LifelikeControl(dict(profile(),lifelike=cfg),clock=lambda:self.now,client_factory=Board,lock_factory=lambda _:Lock());c._guard=lambda:None
  with patch('eye_follow_panel.verified_command',return_value=[]):c.start()
  return c
 def test_forbidden_endpoint_rejected_even_with_old_approval(self):
  cfg=config((21,));p=next(p for p in cfg['poses'] if p['channel']==21);p['forbidden_pulses_us']=[1100,1900]
  self.assertFalse(pose_valid(p));self.assertNotIn(21,approved_poses(cfg)[0])
 def test_jaw_microprobe_bounded_then_off_not_auto_approval(self):
  c=self.make(probe_config());self.assertNotIn(21,c.engine.poses)
  with self.assertRaises(ValueError):c.preview_joint(21,True)
  c.probe_jaw(-1,True)
  seen=[]
  for i in range(110):
   self.now=i*.05;c.tick(.05)
   if c.last_state['active_mask']&(1<<21):seen.append(c.last_state['output_us'][21])
  self.assertTrue(seen);self.assertTrue(all(1475<=u<=1525 for u in seen));self.assertIsNone(c.preview);self.assertEqual(c.last_state['active_mask'],MASK)
  with self.assertRaises(ValueError):c.approve_pose(21)
  c.end(True)
 def test_blink_reports_missing_eye_instead_of_silent_noop(self):
  c=self.make(config((8,)));c.enable_life(True)
  with self.assertRaisesRegex(ValueError,'左上眼帘'):c.life_event({'type':'blink'})
  c.end(True)
 def test_fast_brows_improve_response_without_overshoot(self):
  def move(rate):
   cfg=config((2,));cfg['poses'][0]['action_us']=1900;cfg['poses'][0]['max_rate_us_per_s']=rate
   e=ExpressionEngine(cfg,0,1);e.enable(0);e.step(.6);e.mood='engaged';e.mood_end=5
   values=[e.step(.6+i*.02)[2] for i in range(26)]
   self.assertTrue(all(1500<=v<=1572 for v in values));return values[-1]
  self.assertGreater(move(450),move(150)+5)
if __name__=='__main__':unittest.main()
