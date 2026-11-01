"""Development pitch envelope; never equates command bounds with measured travel."""
def vertical_settings(profile):
    limits=profile.get("development_feedback_limits_us",profile.get("initial_feedback_limits_us",[1450,1550]))
    if not isinstance(limits,list) or len(limits)!=2 or any(type(v) is not int for v in limits):
        raise ValueError("invalid vertical limits")
    if tuple(limits) not in ((1450,1550),(1400,1600),(1100,1900),(1000,2000)):
        raise ValueError("unsupported vertical development envelope")
    if limits in ([1100,1900],[1000,2000]) and not profile.get("matching_horizontal_span_requested_by_operator"):
        raise ValueError("matching horizontal pitch span requires operator request")
    rate=profile.get("development_max_rate_us_per_s",profile.get("initial_max_rate_us_per_s",50))
    if type(rate) is not int or not 1<=rate<=100:raise ValueError("invalid vertical rate")
    return limits[0],limits[1],rate


def vertical_output_settings(profile):
    quantum=profile.get("output_quantum_us",10)
    slew=profile.get("output_slew_us_per_frame",10)
    if type(quantum) is not int or quantum not in (1,2,5,10):
        raise ValueError("unsupported vertical output quantum")
    if type(slew) is not int or not 1<=slew<=10:
        raise ValueError("unsupported vertical hardware slew")
    return quantum,slew
