"""Normalized expression layers; no device, camera, or speech ownership."""
import math
from head_motion import clamp

ALIASES = {'happy': 'smile', '笑': 'smile', '微笑': 'smile', '难过': 'sad',
           '右眼wink': 'wink', 'wink_right': 'wink'}
LABELS = {'smile': '微笑', 'sad': '难过', 'neutral': '自然', 'wink': '右眼 wink'}
# Only existing, observed action directions. Aesthetic acceptance is separate.
# Bilateral pairs are omitted together if either direction is not approved.
RECIPES = {
    'smile': {2: .18, 4: .18, 3: .35, 5: .35, 10: .55, 12: .55,
              11: .10, 13: .10, 14: .45, 16: .45, 15: .65, 17: .65},
    'sad': {2: .75, 4: .75},
}
PAIRS = ((2, 4), (3, 5), (10, 12), (11, 13), (14, 16), (15, 17))
POSE_CHANNELS = (*range(2, 6), *range(10, 18))


def finite_number(value, lo, hi, label):
    if type(value) not in (int, float) or not math.isfinite(value) or not lo <= value <= hi:
        raise ValueError('Invalid ' + label)
    return float(value)


def ease(value):
    x = clamp(value, 0, 1)
    return x*x*x*(10+x*(-15+6*x))


def wink_signature(pose):
    return {key: pose[key] for key in ('channel', 'neutral_us', 'action_us', 'min_us', 'max_us')}


class PresetLayer:
    """Interruptible crossfade; duration includes attack, hold, and release."""
    def __init__(self):
        self.clear()

    def clear(self):
        self.name = 'neutral'; self.event = None

    def sample(self, now):
        if self.event is None:
            return {}, 0.
        start, duration, source, source_mix, target = self.event
        elapsed = max(0., now-start)
        if elapsed >= duration:
            self.clear(); return {}, 0.
        edge = min(.45, duration/3)
        attack = ease(elapsed/edge)
        release = 1-ease((elapsed-(duration-edge))/edge)
        values = {ch: ((1-attack)*source.get(ch, 0.)+attack*target.get(ch, 0.))*release
                  for ch in set(source) | set(target)}
        return values, ((1-attack)*source_mix+attack)*release

    def trigger(self, name, now, duration, intensity, approved):
        name = ALIASES.get(name, name)
        if name not in (*RECIPES, 'neutral'):
            raise ValueError('Unknown expression')
        duration = finite_number(duration, .1, 20, 'expression duration')
        intensity = finite_number(intensity, 0, 1, 'expression intensity')
        source, mix = self.sample(now)
        target = {ch: 0. for ch in POSE_CHANNELS if ch in approved}
        if name != 'neutral':
            recipe = RECIPES[name]
            for left, right in PAIRS:
                if left in approved and right in approved:
                    target[left] = recipe.get(left, 0.)*intensity
                    target[right] = recipe.get(right, 0.)*intensity
            if not any(target.values()):
                raise ValueError('该表情缺少已确认的成对动作方向')
        # Neutral fades the previous layer away; it does not stop speech or gaze.
        self.name = name
        self.event = (now, duration, source, mix, target)


class WinkLayer:
    def __init__(self):
        self.event = None
        self.last_start = -100.

    def trigger(self, now, pose, intensity=.8):
        intensity = finite_number(intensity, .1, 1, 'wink intensity')
        if self.event is not None or now-self.last_start < 1.2:
            raise ValueError('请等待本次 wink 完成')
        distance = abs(pose['action_us']-pose['neutral_us'])*intensity
        close = max(.18, 1.875*distance/pose['max_rate_us_per_s'])
        self.event = (now, close, .18, close*1.4, intensity)
        self.last_start = now

    def sample(self, now):
        if self.event is None:
            return 0.
        start, closing, hold, opening, intensity = self.event
        t = max(0., now-start)
        if t < closing:
            return intensity*ease(t/closing)
        if t < closing+hold:
            return intensity
        if t < closing+hold+opening:
            return intensity*(1-ease((t-closing-hold)/opening))
        self.event = None
        return 0.
