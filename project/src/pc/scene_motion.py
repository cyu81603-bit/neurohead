"""Estimate background image motion; excludes face/body and viewer overlays."""
class SceneMotion:
    def __init__(self):
        import cv2,numpy as np
        self.cv=cv2;self.np=np;self.previous=None;self.previous_mask=None;self.last_time=None
    def mask(self,shape,box):
        cv,np=self.cv,self.np;h,w=shape
        mask=np.full((h,w),255,dtype=np.uint8);mask[:32,:]=0
        cv.rectangle(mask,(w//2-25,h//2-25),(w//2+25,h//2+25),0,-1)
        if box is not None:
            x,y,bw,bh=map(int,box);cx=x+bw//2
            # Exclude head and likely body region, retaining static room background.
            cv.rectangle(mask,(max(0,cx-int(1.2*bw)),max(0,y-15)),
                         (min(w-1,cx+int(1.2*bw)),h-1),0,-1)
            cv.line(mask,(w//2,h//2),(cx,y+bh//2),0,12)
        return mask
    def update(self,rgb,box,frame_time):
        cv,np=self.cv,self.np
        gray=cv.cvtColor(rgb,cv.COLOR_RGB2GRAY);mask=self.mask(gray.shape,box)
        old,oldmask,oldtime=self.previous,self.previous_mask,self.last_time
        self.previous,self.previous_mask,self.last_time=gray,mask,frame_time
        result={"valid":False,"tracked_points":0,"inlier_ratio":0.}
        if old is None or old.shape!=gray.shape or not 0<frame_time-oldtime<.5:return result
        points=cv.goodFeaturesToTrack(old,maxCorners=180,qualityLevel=.015,minDistance=9,mask=oldmask,blockSize=7)
        if points is None or len(points)<8:return result
        moved,status,_=cv.calcOpticalFlowPyrLK(old,gray,points,None,winSize=(21,21),maxLevel=3)
        if moved is None:return result
        a=points.reshape(-1,2);b=moved.reshape(-1,2);good=status.reshape(-1)==1
        h,w=gray.shape
        good&=(b[:,0]>=0)&(b[:,0]<w)&(b[:,1]>=0)&(b[:,1]<h)
        a,b=a[good],b[good]
        if len(b)<8:return result
        inside=mask[b[:,1].astype(int),b[:,0].astype(int)]!=0
        a,b=a[inside],b[inside]
        if len(b)<8:return result
        transform,inliers=cv.estimateAffinePartial2D(a,b,method=cv.RANSAC,ransacReprojThreshold=2.,
                                                   maxIters=1000,confidence=.99)
        if transform is None or inliers is None:return result
        count=int(inliers.sum());ratio=count/len(b)
        result.update(tracked_points=len(b),inlier_ratio=float(ratio))
        if count<8 or ratio<.65:return result
        center=np.array([w/2,h/2,1.])
        delta=transform@center-center[:2]
        import math
        result.update(valid=True,dx_px=float(delta[0]),dy_px=float(delta[1]),dt_s=float(frame_time-oldtime),
            roll_deg=math.degrees(math.atan2(transform[1,0],transform[0,0])),
            image_scale=float(math.hypot(transform[0,0],transform[1,0])))
        return result
