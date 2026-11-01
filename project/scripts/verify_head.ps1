$ErrorActionPreference='Stop'
. F:\NeuroHead\use_f_storage.ps1
$root=Split-Path $PSScriptRoot -Parent
$python='F:\NeuroHead\workspace\neurohead_fpga_2026\build\pybullet_env\python.exe'
foreach($test in @('test_jaw_fixed_points.py','test_jaw_seek.py','test_handoff_client.py','test_neck_speed_v4.py','test_lifelike_v3.py','test_lifelike_v2.py','test_camera_recovery.py','test_lifelike.py','test_22_extension.py','test_pc.py','test_face_commission.py','test_head_transport.py','test_head_motion.py','test_head_control.py','test_head_session.py','test_neck_session.py','test_neck_control.py','test_neck_presets.py','test_neck_transport.py','test_neck_panel.py')){
 & $python (Join-Path $root "sim\$test")
 if($LASTEXITCODE -ne 0){throw "$test failed"}
}
& $python (Join-Path $root 'src\pc\head_follow_panel.py') --self-test
if($LASTEXITCODE -ne 0){throw 'Five-axis panel idle smoke failed'}
& $python (Join-Path $root 'src\pc\face_commission_panel.py') --self-test
if($LASTEXITCODE -ne 0){throw 'Facial panel idle smoke failed'}
& $python (Join-Path $root 'src/pc/lifelike_panel.py') --self-test
if($LASTEXITCODE -ne 0){throw 'Lifelike idle smoke failed'}
Write-Output 'HEAD_EYE_NECK_FACE_LIFE_OFFLINE_PASS: simulated transport only'