import unittest
from conversation_voice import TurnGate


class GateTests(unittest.TestCase):
    def gate(self):
        g=TurnGate()
        for i in range(35):self.assertEqual(g.step(200,i*.032),'calibrating')
        return g
    def test_stationary_noise_does_not_start_infinite_turn(self):
        g=self.gate()
        for i in range(4000):self.assertEqual(g.step(200,2+i*.032),'idle')
        self.assertIsNone(g.started)
    def test_maximum_checked_even_without_a_single_silent_frame(self):
        g=self.gate();phases=[]
        for i in range(600):phases.append(g.step(1500,2+i*.032))
        self.assertIn('maximum',phases)
        self.assertLess(phases.index('maximum'),475)
    def test_sentence_ends_after_pause(self):
        g=self.gate()
        for i in range(8):g.step(1500,2+i*.032)
        result=[g.step(200,2.3+i*.032) for i in range(25)]
        self.assertIn('end',result)
    def test_repeated_turns_can_restart(self):
        g=self.gate()
        for base in (2.,5.):
            phases=[g.step(1200,base+i*.032) for i in range(5)]
            self.assertIn('start',phases)
            phases=[g.step(100,base+.2+i*.032) for i in range(30)]
            self.assertIn('end',phases)


if __name__=='__main__':unittest.main(verbosity=2)
