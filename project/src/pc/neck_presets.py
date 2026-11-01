"""Physical rod motion mapped around separately calibrated PWM references."""
def neck_neutral(profile):
    values=profile.get('manual_neck_reference_us')
    if values is None:values=[profile.get('yaw_reference_pulse_us',1500),*profile.get('pair_reference_us',[1500,1500])]
    if not isinstance(values,list) or len(values)!=3 or any(type(v) is not int or not 1100<=v<=1900 for v in values):
        raise ValueError('neck references must be three integers in 1100..1900')
    return list(values)
def rod_up_signs(profile):
    signs=profile.get('rod_up_pwm_signs')
    if not profile.get('rod_directions_operator_verified') or not isinstance(signs,list) or len(signs)!=2 or any(type(v) is not int or v not in (-1,1) for v in signs):
        raise ValueError('rod PWM polarities need explicit fixed-pose observation')
    return tuple(signs)
def available(value,direction):return 1900-value if direction>0 else value-1100

def side_preset_limit(profile):
    reference=neck_neutral(profile)[1:]
    return min([400]+[v for u in reference for v in (u-1100,1900-u)])
def side_amplitudes(profile):
    limit=side_preset_limit(profile);stored=profile.get('side_preset_spans_us',{})
    if not isinstance(stored,dict):raise ValueError('invalid side preset amplitudes')
    result={}
    for name in ('left_up_right_down','left_down_right_up'):
        value=stored.get(name,limit)
        if type(value) is not int or not 0<=value<=400:raise ValueError('invalid side preset amplitude')
        result[name]=min(value,limit)
    return result
def rod_preset(yaw,left_up,right_up,profile,span=400):
    if type(yaw) is not int or not 1100<=yaw<=1900 or type(span) is not int or not 0<span<=400:
        raise ValueError('unsupported neck preset envelope')
    if left_up not in (-1,0,1) or right_up not in (-1,0,1):raise ValueError('invalid rod directions')
    signs=rod_up_signs(profile);reference=neck_neutral(profile)[1:]
    directions=[up*sign for up,sign in zip((left_up,right_up),signs)]
    travel=min([span]+[available(u,d) for u,d in zip(reference,directions) if d])
    if left_up*right_up==-1 and profile.get('side_presets_balanced',True):
        name='left_up_right_down' if left_up>0 else 'left_down_right_up'
        travel=min(travel,side_amplitudes(profile)[name])
    return [yaw]+[u+d*travel for u,d in zip(reference,directions)]
def rod_shift(values,amount_up,profile):
    if len(values)!=3 or any(type(v) is not int or not 1100<=v<=1900 for v in values):raise ValueError('invalid neck targets')
    if type(amount_up) is not int or abs(amount_up)>50:raise ValueError('rod step too large')
    signs=rod_up_signs(profile);directions=[s*(1 if amount_up>=0 else -1) for s in signs]
    travel=min([abs(amount_up)]+[available(u,d) for u,d in zip(values[1:],directions)])
    return [values[0]]+[u+d*travel for u,d in zip(values[1:],directions)]