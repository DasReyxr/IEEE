#!/usr/bin/env bash
# Empaqueta la app como un binario portable de Linux.
# Ejecutar dentro de un venv con las dependencias instaladas (ver README.md).
set -e

pyinstaller --onefile --windowed \
    --name IEEE_vTools_Filler \
    --collect-all playwright \
    --collect-all tkcalendar \
    --hidden-import babel.numbers \
    gui_app.py

echo
echo "Listo. El binario queda en dist/IEEE_vTools_Filler"
echo "Copia tu archivo .env (con IEEE_USER / IEEE_PASS) junto al binario."
