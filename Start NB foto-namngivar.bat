@echo off
REM Dobbeltklikk denne fila for a starte appen. Nettlesaren opnar seg sjolv.
title NB foto-namngivar
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0start-app.ps1"
echo.
echo Appen er stoppa. Du kan lukke dette vindauget.
pause
