@echo off
REM Empaqueta la app como un .exe portable de Windows.
REM Ejecutar dentro de un venv con las dependencias instaladas (ver README.md).

pyinstaller --onefile --windowed ^
    --name IEEE_vTools_Filler ^
    --collect-all playwright ^
    --collect-all tkcalendar ^
    --hidden-import babel.numbers ^
    gui_app.py

echo.
echo Listo. El ejecutable queda en dist\IEEE_vTools_Filler.exe
echo Copia tu archivo .env (con IEEE_USER / IEEE_PASS) junto al .exe.
pause
