$ErrorActionPreference='Stop'
. F:\NeuroHead\use_f_storage.ps1
$root=Split-Path $PSScriptRoot -Parent
$out=Join-Path $root 'build\verification'
New-Item -ItemType Directory -Force -Path $out | Out-Null
& 'C:\iverilog\bin\iverilog.exe' -g2012 -s tb_nh22 -o "$out\tb.vvp" "$root\src\rtl\nh22_axi.sv" "$root\sim\tb_nh22.sv"
if($LASTEXITCODE -ne 0){throw 'RTL compile failed'}
& 'C:\iverilog\bin\vvp.exe' "$out\tb.vvp" | Tee-Object -FilePath "$out\rtl.log"
if($LASTEXITCODE -ne 0){throw 'RTL failed'}
& 'D:\MinGW\bin\gcc.exe' -std=c11 -Wall -Wextra -Werror -I "$root\src\ps" "$root\sim\test_protocol.c" "$root\src\ps\nh22_protocol.c" -o "$out\protocol_test.exe"
if($LASTEXITCODE -ne 0){throw 'Protocol compile failed'}
& "$out\protocol_test.exe" | Tee-Object -FilePath "$out\protocol.log"
if($LASTEXITCODE -ne 0){throw 'Protocol failed'}
foreach($test in @('test_pc.py','test_vision.py','test_bench.py','test_requalification.py','test_loaded_visual.py','test_eye_span.py','test_visible_visual.py','test_image_feedback.py','test_eye_feedback_runner.py','test_continuous_follow.py','test_bench_exclusion.py','test_vertical_setup.py','test_vertical_feedback.py','test_dual_feedback.py','test_vertical_range100.py','test_pitch_response.py','test_effective_pulse.py','test_effective_pulse_runner.py','test_matching_eye_span.py','test_neck_setup.py','test_neck_yaw_probe.py','test_neck_pair_midpoint.py','test_neck_pair_probe.py','test_neck_identification.py','test_neck_control.py','test_neck_transport.py','test_neck_presets.py','test_neck_coordinates.py','test_neck_session.py')){
 & 'C:\Python39\python.exe' "$root\sim\$test"
 if($LASTEXITCODE -ne 0){throw "$test failed"}
}
& 'C:\iverilog\bin\iverilog.exe' -g2012 -s tb_nh22_50mhz -o "$out\pwm50.vvp" "$root\src\rtl\nh22_axi.sv" "$root\sim\tb_nh22_50mhz.sv"
if($LASTEXITCODE -ne 0){throw '50MHz compile failed'}
& 'C:\iverilog\bin\vvp.exe' "$out\pwm50.vvp" | Tee-Object -FilePath "$out\pwm50.log"
if($LASTEXITCODE -ne 0){throw '50MHz timing failed'}
Write-Output 'NH22_OFFLINE_VERIFICATION_PASS'
