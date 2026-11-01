import sys,unittest
from pathlib import Path
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1];sys.path[:0]=[str(ROOT/'src/pc'),str(ROOT/'sim')]
from test_lifelike import config
from test_lifelike_v2 import probe_config
from lifelike_behavior import ExpressionEngine
from lifelike_control import LifelikeControl
from test_head_control import profile,Lock
from test_face_commission import Board
class V3Tests(unittest.TestCase):
 def test_larger_brow_stretch_stays_in_confirmed_range(self):
  def run(style):
   cfg=config((2,));cfg.update(expression_style=style,stretch_duration_s=1.1)
   cfg['poses'][0].update(action_us=1900,max_rate_us_per_s=900)
   e=ExpressionEngine(cfg,0,1);e.enable(0);e.step(.6);e.stretch_start=.6;e.next_stretch=100
   v=[e.step(.6+i*.02)[2] for i in range(80)]
   self.assertTrue(all(1100<=u<=1900 for u in v));return max(v)
  self.assertGreater(run('active'),run('classic')+70)
 def test_lips_have_clearer_speech_excursion_and_return(self):
  def run(style):
   cfg=config((10,));cfg['poses'][8].update(action_us=1900,max_rate_us_per_s=1800);cfg['expression_style']=style
   e=ExpressionEngine(cfg,0,1);e.enable(0);e.step(.6);e.speech.timeline([1.]*50+[0.]*150,.02,.6)
   v=[e.step(.6+i*.02)[10] for i in range(200)]
   self.assertAlmostEqual(v[-1],1500,delta=1);return max(v)
  self.assertGreater(run('active'),run('classic')+100)
 def test_demo_leaves_jaw_disabled_and_finishes_speech(self):
  cfg=probe_config();cfg.update(expression_style='active',stretch_duration_s=1.1)
  for p in cfg['poses']:
   if 2<=p['channel']<=13:p.update(enabled=True,action_verified=True)
  Board.instances=[];Board.fail=False;clock=[0.]
  c=LifelikeControl(dict(profile(),lifelike=cfg),clock=lambda:clock[0],client_factory=Board,lock_factory=lambda _:Lock());c._guard=lambda:None
  with patch('eye_follow_panel.verified_command',return_value=[]):c.start()
  c.enable_life(True);c.demo_expressions();self.assertTrue(c.engine.blink)
  for i in range(200):
   clock[0]=i*.05;c.tick(.05);self.assertFalse(c.last_state['active_mask']&(1<<21))
  self.assertIsNone(c.engine.speech.kind)
  for style in ['soft','lively','active']:self.assertEqual(c.set_expression_style(style)['expression_style'],style)
  with self.assertRaises(ValueError):c.set_expression_style('invalid')
  c.end(True)
if __name__=='__main__':unittest.main()
