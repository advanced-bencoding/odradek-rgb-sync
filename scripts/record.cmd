@echo off
rem Record every animation change in the game while you play, to map new states (CONTRIBUTING.md,
rem "Mapping a new Odradek state"). Usage: scripts\record.cmd [label]   Ctrl+C stops.
rem Writes recordings\<date>-<time>-<label>.jsonl (git ignores it: recordings are personal data).
rem While it records, type a note and press Enter (e.g. "pool now") to drop a marker in the log.
setlocal
cd /d "%~dp0.."
set "LABEL=%~1"
if "%LABEL%"=="" set "LABEL=session"
for /f %%t in ('powershell -NoProfile -Command "Get-Date -Format yyyyMMdd-HHmmss"') do set "TS=%%t"
if not exist recordings mkdir recordings
echo recording to recordings\%TS%-%LABEL%.jsonl
".venv\Scripts\odradek-sync.exe" recon watch --all --ignore "" --log "recordings\%TS%-%LABEL%.jsonl"
