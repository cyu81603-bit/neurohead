"""Export honest camera/model/PL observations; no inference of physical tracking."""
import csv
import json
import math
from pathlib import Path
import statistics


def stats(values):
    data=sorted(float(x) for x in values if isinstance(x,(int,float)) and math.isfinite(x) and x>=0)
    if not data:return None
    return dict(n=len(data),median=statistics.median(data),p95=data[max(0,math.ceil(len(data)*.95)-1)],max=data[-1])


def export_session(run_dir):
    directory=Path(run_dir)
    rows=[];ignored=0
    for line in (directory/'frames.jsonl').read_text(encoding='utf-8').splitlines():
        try:
            row=json.loads(line)
            if not isinstance(row,dict):raise ValueError('not a row')
            rows.append(row)
        except ValueError:ignored+=1
    vision_rows=[];seen=set();states=[];rtts=[];board_fresh=0
    native_rows=[];native_seen=set()
    for row in rows:
        v=row.get('vision')
        if v and v.get('frame_id',0)>0:
            key=(v.get('source_session_id','legacy'),v['frame_id'])
            if key not in seen:
                seen.add(key);vision_rows.append(v)
        b=row.get('board_monitor') or {}
        if row.get('mode') in ('board','vision_board') and b.get('fresh'):
            board_fresh+=1
            if b.get('last_rtt_ms') is not None:rtts.append(b['last_rtt_ms'])
        if row.get('gaze_status') is not None:states.append(row['gaze_status'])
        controller=row.get('controller_diagnostics') or {}
        stamp=controller.get('input_time');now=row.get('host_monotonic_s')
        fresh=(isinstance(stamp,(int,float)) and isinstance(now,(int,float)) and 0<=now-stamp<=.5)
        native_key=(controller.get('log_dir'),controller.get('response_sequence'))
        if (controller.get('backend')=='visp_native' and controller.get('metrics') and fresh
                and not controller.get('error') and native_key not in native_seen):
            native_seen.add(native_key);native_rows.append(controller)
    losses=sum(a=='tracking' and b!='tracking' for a,b in zip(states,states[1:]))
    reacquired=sum(a!='tracking' and b=='tracking' for a,b in zip(states,states[1:]))
    report=dict(rows=len(rows),ignored_incomplete_or_invalid_lines=ignored,
                modes=sorted({row.get('mode','unknown') for row in rows}),
                unique_sampled_camera_frames=len(vision_rows),
                sampled_face_positive_frames=sum(v.get('face_count',0)>0 for v in vision_rows),
                sampled_gaze_loss_transitions=losses,sampled_gaze_reacquisitions=reacquired,
                render_ms=stats(row.get('render_ms') for row in rows),
                sampled_window_frame_period_ms=stats(row.get('frame_period_ms') for row in rows),
                sampled_detection_ms=stats(v.get('detection_ms') for v in vision_rows),
                unique_fresh_native_visp_samples=len(native_rows),
                native_visp_compute_ms=stats(c.get('compute_ms') for c in native_rows),
                virtual_visp_error_norm=stats(c['metrics'].get('virtual_error_norm') for c in native_rows),
                native_visp_calls_max_observed=max((c['metrics'].get('native_compute_calls',0) for c in native_rows),default=0),
                fresh_board_observation_rows=board_fresh,
                sampled_host_poll_rtt_ms=stats(rtts),
                board_queries_max_observed=max(((row.get('board_monitor') or {}).get('queries',0) for row in rows),default=0),
                board_replies_max_observed=max(((row.get('board_monitor') or {}).get('replies',0) for row in rows),default=0),
                application_motion_commands_max=max((row.get('hardware_motion_commands_sent',0) for row in rows),default=0),
                camera_images_saved=0,physical_angle_measured=False,physical_tracking_validated=False,
                boundaries=['Camera centre offset is input, not closed-loop tracking error.',
                    'Model degrees are virtual; PL microseconds are settings, not measured shaft angle.',
                    'Host poll RTT includes scheduling; it is not one-way or camera-to-motion latency.',
                    'Counts/rates are sampled observations, not a sustained camera FPS benchmark.',
                    'Command count describes this application, not a separate packet-capture audit.'])
    report['boundaries'].append('ViSP residuals are virtual-camera model errors, not measured physical tracking errors.')
    with (directory/'measurements.csv').open('w',newline='',encoding='utf-8-sig') as file:
        fields=['mode','host_monotonic_s','camera_frame','face_count','input_x','input_y',
                'virtual_eye_pan_deg','virtual_neck_pan_deg','virtual_eye_tilt_deg','virtual_neck_tilt_deg',
                'render_ms','frame_period_ms','render_quality','board_fresh','pl_yaw_setting_us','pl_pitch_setting_us','gaze_status',
                'input_kind','controller_backend','controller_response_sequence','controller_error',
                'native_compute_ms','native_calls','virtual_visp_error_x','virtual_visp_error_y','virtual_visp_error_norm']
        writer=csv.DictWriter(file,fieldnames=fields);writer.writeheader()
        for row in rows:
            v=row.get('vision') or {};target=v.get('target') or row.get('synthetic_target') or [None,None]
            pose=row.get('model_degrees') or {};b=row.get('board_monitor') or {};s=b.get('state') or {}
            controller=row.get('controller_diagnostics') or {};metrics=controller.get('metrics') or {}
            residual=metrics.get('virtual_image_error') or [None,None]
            writer.writerow(dict(mode=row.get('mode'),host_monotonic_s=row.get('host_monotonic_s'),
                camera_frame=v.get('frame_id'),face_count=v.get('face_count'),input_x=target[0],input_y=target[1],
                virtual_eye_pan_deg=pose.get('eye_pan'),virtual_neck_pan_deg=pose.get('neck_pan'),
                virtual_eye_tilt_deg=pose.get('eye_tilt'),virtual_neck_tilt_deg=pose.get('neck_tilt'),
                render_ms=row.get('render_ms'),frame_period_ms=row.get('frame_period_ms'),
                render_quality=row.get('render_quality'),board_fresh=b.get('fresh'),
                pl_yaw_setting_us=s.get('output_yaw_us'),pl_pitch_setting_us=s.get('output_pitch_us'),
                gaze_status=row.get('gaze_status'),
                input_kind='synthetic_target' if row.get('mode')=='visp_demo' else 'camera_centroid_offset' if v else 'none',
                controller_backend=controller.get('backend'),controller_response_sequence=controller.get('response_sequence'),
                controller_error=controller.get('error'),native_compute_ms=controller.get('compute_ms'),
                native_calls=metrics.get('native_compute_calls'),virtual_visp_error_x=residual[0],
                virtual_visp_error_y=residual[1],virtual_visp_error_norm=metrics.get('virtual_error_norm')))
    (directory/'summary.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    text=f'''# 运行观测报告

模式：{', '.join(report['modes'])}。有效日志{len(rows)}条，忽略不完整/无效行{ignored}条。

- 采样到的唯一相机帧：{len(vision_rows)}；其中有人脸：{report['sampled_face_positive_frames']}。
- 采样状态中的目标丢失/重新获得：{losses}/{reacquired}。
- 新鲜真实板卡观测：{board_fresh}条；查询/回复最大观测值：{report['board_queries_max_observed']}/{report['board_replies_max_observed']}。
- 本应用运动命令最大观测计数：{report['application_motion_commands_max']}。
- 渲染耗时统计（ms）：{report['render_ms']}。
- 窗口更新间隔采样统计（ms，包含渲染与界面开销，不是相机帧率）：{report['sampled_window_frame_period_ms']}。
- 检测耗时采样统计（ms）：{report['sampled_detection_ms']}。
- ViSP原生新鲜结果去重采样：{report['unique_fresh_native_visp_samples']}；单次工作进程计算计数最大观测值：{report['native_visp_calls_max_observed']}。
- ViSP原生计算耗时（ms）：{report['native_visp_compute_ms']}；虚拟相机误差范数：{report['virtual_visp_error_norm']}（非实物闭环误差）。

原始日志：frames.jsonl；可分析数据：measurements.csv；机器可读汇总：summary.json。

图像中心偏移只是输入，不是闭环跟踪误差。虚拟角度不是实际角度；PL脉宽回读只是设置。没有真实关节位置或机械端到端延迟测量。本次不宣称真实追踪验证通过。

RTT包含主机轮询调度，不是单程时延。相机统计来自抽样观测，不能直接当持续帧率基准。运动命令计数只描述本程序，不是独立抓包审计。旧版日志无source_session_id时，重复打开相机的采样帧数可能被低估。
'''
    path=directory/'summary.md';path.write_text(text,encoding='utf-8')
    return path,report
