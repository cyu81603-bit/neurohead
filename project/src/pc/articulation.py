"""PCM speech energy with short closing gaps; no actuator or audio-device IO."""
import math
import numpy as np


def speech_envelope(pcm, rate=16000, records=None, step=.02):
    samples=np.asarray(pcm,dtype=np.float64).reshape(-1)/32768.
    if not len(samples) or not 8000<=rate<=96000 or not .005<=step<=.1:
        raise ValueError('Invalid PCM speech envelope')
    size=max(1,round(rate*step))
    rms=np.array([float(np.sqrt(np.mean(samples[i:i+size]**2))) for i in range(0,len(samples),size)])
    scale=max(.015,float(np.percentile(rms,90)))
    energy=np.clip((rms-max(.003,scale*.08))/(scale*.92),0,1)**.65
    energy=np.where(energy>.06,.65+.35*energy,0.)
    # Group short character windows so the existing mechanical rate can both open
    # and close. Character alignment is approximate; silence always wins.
    spans=[];start=end=None
    for r in records or []:
        a=float(r['start_ms'])/1000;b=float(r['end_ms'])/1000
        if not math.isfinite(a+b) or not 0<=a<b<=len(samples)/rate+.2:continue
        if start is None:start,end=a,b
        elif a-end>.08 or end-start>=.45:
            spans.append((start,end));start,end=a,b
        else:end=b
    if start is not None:spans.append((start,end))
    for i in range(len(energy)):
        t=i*step
        if spans:
            span=next(((a,b) for a,b in spans if a<=t<b),None)
            if span is None:energy[i]=0.;continue
            a,b=span;parts=max(1,round((b-a)/.60));period=(b-a)/parts
            phase=((t-a)%period)/period
        else:
            # Long continuous voiced runs still have visible articulation.
            phase=(t%.60)/.60
        if phase<.10:gate=phase/.10
        elif phase<.50:gate=1.
        elif phase<.60:gate=(.60-phase)/.10
        else:gate=0.
        energy[i]*=gate
    return [float(x) for x in energy],step
