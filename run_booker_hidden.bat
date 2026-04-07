@echo off
cd /d "%~dp0"
python booker.py --players 4 --holes 18 --earliest-hour 8 --latest-hour 10 --headless