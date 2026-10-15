@echo off
chcp 65001 > nul
echo =================================================================
echo   CONVRAIN - Precision Satellite Convective Nowcast Platform (HUD)
echo =================================================================
echo.
cd /d "%~dp0"
echo กำลังเริ่มต้น Web Server ที่ http://localhost:8500 ...
python run_web.py --port 8500 --data-dir CONVRAIN_OUTPUT
pause
