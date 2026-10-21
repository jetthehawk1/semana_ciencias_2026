# Disaster Command Center — Semana de Ciencias 2026

La única carpeta de aplicación es **[DisasterCommandCenter/](DisasterCommandCenter/README.md)**.
Contiene simulación/Pygame (Persona 1), datos e IA (Persona 2), rutas
(Persona 3), contratos, datos necesarios y pruebas.

~~~powershell
cd DisasterCommandCenter
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python main.py
~~~

Pruebas: `python tools/run_tests.py` desde esa carpeta. PostgreSQL es opcional.
Los sensores y datasets son sintéticos.

Consulta el [README de la aplicación](DisasterCommandCenter/README.md) y
[INTEGRATION_FEEDBACK.md](DisasterCommandCenter/INTEGRATION_FEEDBACK.md).

`Chagoya/` se conserva como implementación histórica alternativa y trabajo
local de su autor. No es dependencia de la aplicación consolidada ni se
mezcla con el contrato de sensores principal.
