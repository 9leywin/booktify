@echo off
rem Prefer the built executable; fall back to running from source.
setlocal
if exist "%~dp0dist\Booktify\Booktify.exe" (
    start "" "%~dp0dist\Booktify\Booktify.exe"
    goto :eof
)
if defined BT_PYTHON (
    set "PY=%BT_PYTHON%"
    goto run
)
if exist "C:\utilities\bin\pythonw.exe" (
    set "PY=C:\utilities\bin\pythonw.exe"
    goto run
)
start "" pyw -3 -m bt.gui
goto :eof

:run
start "" "%PY%" -m bt.gui
