"""Logical 1100..1900 with logical center 1500, calibrated hardware endpoints."""
from neck_presets import neck_neutral
LO,HI,CENTER=1100,1900,1500
def logical_to_pwm(position,channel_index,profile):
    if not isinstance(position,(int,float)) or not LO<=position<=HI or channel_index not in (0,1,2):
        raise ValueError('invalid logical neck position')
    neutral=neck_neutral(profile)[channel_index]
    if position<=CENTER:return round(LO+(position-LO)*(neutral-LO)/(CENTER-LO))
    return round(neutral+(position-CENTER)*(HI-neutral)/(HI-CENTER))
def pwm_to_logical(pwm,channel_index,profile):
    if not isinstance(pwm,(int,float)) or not LO<=pwm<=HI or channel_index not in (0,1,2):
        raise ValueError('invalid physical neck PWM')
    neutral=neck_neutral(profile)[channel_index]
    if pwm<=neutral:
        return CENTER if neutral==LO else round(LO+(pwm-LO)*(CENTER-LO)/(neutral-LO))
    return CENTER if neutral==HI else round(CENTER+(pwm-neutral)*(HI-CENTER)/(HI-neutral))
def pose_to_pwm(positions,profile):
    if len(positions)!=3:raise ValueError('three logical coordinates required')
    return [logical_to_pwm(v,i,profile) for i,v in enumerate(positions)]
def pose_to_logical(pulses,profile):
    if len(pulses)!=3:raise ValueError('three physical pulse values required')
    return [pwm_to_logical(v,i,profile) for i,v in enumerate(pulses)]