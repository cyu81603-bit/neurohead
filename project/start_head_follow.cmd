@echo off
call F:\NeuroHead\use_f_storage.cmd
cd /d "%~dp0"
start "" "F:\NeuroHead\workspace\neurohead_fpga_2026\build\pybullet_env\pythonw.exe" "%~dp0src\pc\head_follow_panel.py"