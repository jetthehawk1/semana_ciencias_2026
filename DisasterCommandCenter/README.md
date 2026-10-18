# Disaster Command Center - Persona 1

## Descripcion
Simulador de evacuacion de un campus universitario
desarrollado en Python y Pygame.

Proyecto Semana de Ciencias 2026.

## Funcionalidades
- Mapa digital del campus de 160 x 100 celdas.
- Simulacion de personas y evacuacion.
- Incendios, humo y viento.
- 12 sensores virtuales.
- Estadisticas y exportacion de datos.
- Administrador original y optimizado.

## Instalacion

Se recomienda Python 3.13.

1. Abrir una terminal en esta carpeta.
2. Crear el entorno virtual:

   python -m venv .venv

3. Activar el entorno en Windows PowerShell:

   .\.venv\Scripts\Activate.ps1

4. Instalar dependencias:

   pip install -r requirements.txt

## Ejecutar el simulador

python main_unificado_14_4_4.py

Para iniciar temporalmente en modo original:

python main_unificado_14_4_4.py --modo-original

Si no existe configuracion de modo, se usa original.

## Controles
A: Iniciar alarma
ESPACIO: Pausar o reanudar
R: Reiniciar
M: Cambiar administrador antes de la alarma
T: Cambiar escenario antes de la alarma
V: Cambiar viento
E: Exportar datos de sensores
S: Mostrar u ocultar sensores
F: Encuadrar campus
ESC: Salir

## Estructura
src/simulation/ - Motores de simulacion.
src/dcc_app/ - Interfaz Pygame.
src/integration/ - Interfaces para otras personas.
data/ - Mapa, accesos y configuracion de sensores.

## Integracion del equipo
Persona 1: simulacion del entorno.
Persona 2: datos, sensores, almacenamiento e IA.
Persona 3: rutas de evacuacion e interfaz.

Las interfaces para Personas 2 y 3 estan preparadas,
pero sus modulos finales aun requieren integracion.

## Nota
Los sensores, incendios y evacuaciones utilizan
datos sinteticos con fines de simulacion.
