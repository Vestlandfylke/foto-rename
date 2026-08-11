@echo off
REM Dobbeltklikk denne fila for a sette opp NB foto-namngivar (Python, venv, avhengnader).
title Installer - NB foto-namngivar
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0setup.ps1"
echo.
pause
