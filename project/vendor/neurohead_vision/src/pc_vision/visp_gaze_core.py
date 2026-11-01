"""Native ViSP control for an explicitly virtual two-axis gaze camera.

GPL-2.0-or-later. Uses ViSP Servo/FeaturePoint, following the upstream v3.7.0
four-point IBVS tutorial (third_party/visp_3_7/provenance.json). The two-axis
camera Jacobian and eye/head allocation below are our uncalibrated model.
This module contains no actuator IO, pulse conversion or measured joint angle.
"""
import math
import numpy as np
from visp.core import HomogeneousMatrix, Matrix
from visp.visual_features import FeaturePoint
from visp.vs import Servo


def clamp(value, low, high):
    return max(low, min(high, value))


class VispGaze:
    def __init__(self):
        self.pose = dict(neck_pan=0., neck_tilt=0., neck_roll=0.,
                         eye_pan=0., eye_tilt=0., jaw_open=0.)
        self.last_time = self.last_seen = None
        self.desired = (0., 0.)
        self.status = 'waiting'
        # Keep Python references alive: vpServo registers these feature objects.
        self.current, self.goal = FeaturePoint(), FeaturePoint()
        self.current.buildFrom(0., 0., 1.)
        self.goal.buildFrom(0., 0., 1.)
        self.task = Servo()
        self.task.setServo(Servo.EYEINHAND_L_cVe_eJe)
        self.task.setInteractionMatrixType(Servo.CURRENT, Servo.PSEUDO_INVERSE)
        self.task.setLambda(2.)
        self.task.addFeature(self.current, self.goal)
        self.task.set_cVe(HomogeneousMatrix())
        self.calls = 0
        self.metrics = {}

    def step(self, target, frame_time, now):
        if not isinstance(now, (int, float)) or not math.isfinite(now):
            raise ValueError('Finite monotonic timestamp required')
        dt = .05 if self.last_time is None else clamp(now-self.last_time, 0., .15)
        self.last_time = now
        fresh = (isinstance(frame_time, (int, float)) and math.isfinite(frame_time)
                 and 0 <= now-frame_time <= .5)
        valid = (fresh and isinstance(target, (list, tuple)) and len(target) == 2
                 and all(isinstance(x, (int, float)) and math.isfinite(x) for x in target))
        if valid:
            nx, ny = (clamp(float(x), -1., 1.) for x in target)
            nx, ny = (0. if abs(x) < .04 else x for x in (nx, ny))
            # Assumed display bearings, NOT real camera intrinsics/extrinsics.
            self.desired = (math.radians(nx*28.), math.radians(ny*16.))
            self.last_seen = frame_time
            self.status = 'tracking'
        elif self.last_seen is not None and 0 <= now-self.last_seen <= .6:
            self.status = 'brief_target_loss'
        else:
            self.desired = (0., 0.)
            self.status = 'no_target' if fresh else 'camera_stale'
        yaw = math.radians(self.pose['neck_pan']+self.pose['eye_pan'])
        pitch = math.radians(self.pose['neck_tilt']+self.pose['eye_tilt'])
        cy, sy, cp, sp = math.cos(yaw), math.sin(yaw), math.cos(pitch), math.sin(pitch)
        # Virtual camera-to-world R = Ry(yaw) Rx(-pitch).
        rotation = np.array([[cy, -sy*sp, sy*cp], [0., cp, sp], [-sy, -cy*sp, cy*cp]])
        point = rotation.T @ np.array([math.tan(self.desired[0]), math.tan(self.desired[1]), 1.])
        if point[2] <= .05:
            raise ValueError('Virtual target behind camera')
        self.current.buildFrom(float(point[0]/point[2]), float(point[1]/point[2]), float(point[2]))
        # End effector frame coincides with virtual camera. Only rotational rows
        # are nonzero. qdot = [virtual yaw rate, virtual downward-pitch rate].
        jacobian = np.zeros((6, 2))
        jacobian[4, 0], jacobian[5, 0] = cp, sp
        jacobian[3, 1] = -1.
        self.task.set_eJe(Matrix(jacobian))
        velocity = np.asarray(self.task.computeControlLaw()).reshape(-1)
        self.calls += 1
        if velocity.shape != (2,) or not np.isfinite(velocity).all():
            raise ValueError('Invalid native ViSP velocity')
        rates = [clamp(math.degrees(float(velocity[0])), -45., 45.),
                 clamp(math.degrees(float(velocity[1])), -30., 30.)]
        total = [clamp(math.degrees(yaw)+rates[0]*dt, -36., 36.),
                 clamp(math.degrees(pitch)+rates[1]*dt, -22., 22.)]
        alpha = -math.expm1(-dt/.65)
        for axis, value, deadband, head_limit, eye_limit in (
                ('pan', total[0], 10., 18., 18.), ('tilt', total[1], 5., 10., 12.)):
            head = 'neck_'+axis
            goal = clamp(math.copysign(max(0., abs(value)-deadband), value), -head_limit, head_limit)
            self.pose[head] += alpha*(goal-self.pose[head])
            self.pose['eye_'+axis] = clamp(value-self.pose[head], -eye_limit, eye_limit)
        error = np.asarray(self.task.getError()).reshape(-1)
        self.metrics = dict(backend='ViSP 3.7 Servo', native_compute_calls=self.calls,
                            virtual_image_error=error.tolist(), virtual_error_norm=float(np.linalg.norm(error)),
                            virtual_velocity_deg_s=rates, model_only=True,
                            physical_camera_calibrated=False, angles_measured=False)
        return dict(self.pose)
