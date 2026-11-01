"""Validated fixed jaw endpoints and speech timing. No device/network IO."""
import math


def fixed_point_plan(jaw):
    if not jaw or jaw.get('drive_mode') != 'fixed_points':
        return None
    record = jaw.get('fixed_point_calibration', {})
    if not isinstance(record, dict):
        raise ValueError('Invalid fixed-point calibration record')
    closed, opened = jaw.get('closed_us'), jaw.get('observed_open_us')
    if (not jaw.get('fixed_point_verified') or not jaw.get('operator_open_observed')
            or record.get('operator_verified') is not True
            or any(type(v) is not int or not 600 <= v <= 2400 for v in (closed, opened))
            or not 0 < abs(closed-opened) <= 100
            or record.get('closed_us') != closed or record.get('open_us') != opened
            or type(record.get('max_change_us_per_frame')) is not int
            or record['max_change_us_per_frame'] != abs(closed-opened)):
        raise ValueError('下颚两点标定不匹配，需要重新验证后才能启用')
    timing = dict(min_open_s=.20, min_closed_s=.30, max_open_s=.45,
                  close_hold_s=3., open_threshold=.35, close_threshold=.15)
    settings = jaw.get('fixed_point_timing', {})
    if not isinstance(settings, dict):
        raise ValueError('Invalid fixed-point jaw timing')
    timing.update(settings)
    if (any(type(v) not in (int, float) or not math.isfinite(v) for v in timing.values())
            or not .1 <= timing['min_open_s'] <= timing['max_open_s'] <= 2.
            or not .1 <= timing['min_closed_s'] <= 2.
            or not 1. <= timing['close_hold_s'] <= 5.
            or not 0. <= timing['close_threshold'] < timing['open_threshold'] <= 1.):
        raise ValueError('Invalid fixed-point jaw timing')
    return dict(timing, closed_us=closed, open_us=opened,
                frame_step_us=record['max_change_us_per_frame'])


class FixedPointJaw:
    def __init__(self, plan, now=0.):
        self.plan = plan
        self.is_open = False
        self.changed_at = now

    def close(self, now):
        if self.is_open:
            self.is_open = False
            self.changed_at = now
        return self.plan['closed_us']

    def step(self, now, energy, speaking, active=True):
        # Stop, silence and expired speech always request the verified closed point.
        if not active or not speaking:
            return self.close(now)
        age = max(0., now-self.changed_at)
        if self.is_open:
            if (age >= self.plan['max_open_s']
                    or (energy <= self.plan['close_threshold']
                        and age >= self.plan['min_open_s'])):
                self.close(now)
        elif energy >= self.plan['open_threshold'] and age >= self.plan['min_closed_s']:
            self.is_open = True
            self.changed_at = now
        return self.plan['open_us'] if self.is_open else self.plan['closed_us']
