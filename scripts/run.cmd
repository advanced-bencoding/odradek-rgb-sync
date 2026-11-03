@echo off
rem Mirror the Odradek on the keyboard while you play; Ctrl+C stops. Usage: scripts\run.cmd [run options]
rem e.g. scripts\run.cmd --subtle
cd /d "%~dp0.."
".venv\Scripts\odradek-sync.exe" run %*
