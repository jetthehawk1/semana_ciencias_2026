# Disaster Command Center — Semana de Ciencias 2026

## Séptima fase: evacuación interior preventiva y presentación

Estado validado: **READY** según los criterios de esta fase. En los mismos
16 escenarios, los contactos medios fueron **2.50 Traditional / 2.25 Intelligent**
(40 / 36 totales; Intelligent anterior: 47). Los contactos interiores se redujeron,
pero siguen presentes: E16 continúa peor que Traditional en dos escenarios.
El episodio aislado de 240 turnos midió **0.7043 s/turno**, frente a 0.6483;
cumple el objetivo de <=0.75. La suite aprobó **43 scripts y 372 pruebas**, sin
omisiones. No se cambiaron física ni puertas para obtener estos resultados.

`python main.py` abre por defecto **Presentation Mode**, en español, con el mapa,
modo, viento, alumnos en zona segura/evacuando/dentro/incapacitados, niveles de
fuego/humo y zonas disponibles. **D** alterna detalles técnicos y vuelve a la
presentación; es un cambio visual. El clic antes de A conserva la selección del
foco; después inspecciona alumnos. No se crean focos nuevos por clic tras iniciar.

Controles visibles: **A** iniciar, **ESPACIO** pausa, **+ / −** reproducción,
**V** dirección de viento, **H** humo, **D** detalles. Se conservan rueda/zoom,
arrastre derecho, reinicio R y los controles históricos. Cambiar reproducción
no cambia la física por turno ni permite mover más de una celda por alumno.

La política interior Intelligent usa `NextTurnFireThreat` y refugios interiores
compartidos dentro de AdaptiveExitController. No cambia fuego/humo, RNG, puertas,
Traditional ni el orden peligro → exposición → movimiento. La máscara es una
precaución aproximada de tres turnos, no una predicción exacta de ignición.
Los edificios con un único grupo de salida reciben prioridad adicional solo
cuando se encuentran amenazados; no se añadieron puertas.
La prioridad no debe desperdiciar un paso por ocupación: si un vecino libera
una celda después del primer intento, una cola de dependencias puede despertar
al alumno que esperaba. Se reutiliza el mismo paso interior y se excluye a
quien ya se movió; se mantiene máximo una celda por alumno y turno. Traditional
y legacy conservan su pasada original. La física no se reordena.

Configuración visual en `presentation`: incendio BAJO <20 celdas activas,
MEDIO 20–99, ALTO >=100; humo BAJO <150 celdas con concentración >=0.05,
MEDIO 150–999, ALTO >=1000. Viento LENTO <0.33, MEDIO <0.66, RÁPIDO >=0.66.
Estos niveles son didácticos, no alertas físicas certificadas. Los cuatro
conteos de alumnos son disjuntos y suman 1879; EN ZONA SEGURA excluye alumnos
incapacitados y exige una reunión actualmente habilitada. No significa vidas
salvadas ni certificación de seguridad. La simulación sigue vigilando reuniones.
Al pausar desde el turno 240 aparece un resumen; no se detiene el motor por un
límite artificial ni se presenta una pausa como evacuación completada.

Pruebas y medición de esta fase:

```powershell
python tests/test_seventh_functional_changes.py
python tools/profile_evacuation.py --turns 240 --output-dir reports/septima_fase --profile
python tools/compare_evacuation_modes_v3.py --workers 3
```

El benchmark v3 reutiliza las definiciones de los **mismos 16 escenarios** de
sexta fase y escribe en `reports/evacuation_comparison_v3/`; los resultados de
sexta permanecen en v2. Los datos siguen siendo sintéticos. El diagnóstico y
la clasificación final están en `SEVENTH_FUNCTIONAL_CHANGES_FEEDBACK.md`.
La sección de sexta fase siguiente es referencia histórica.


Simulación universitaria de evacuación ante incendios en UABC Unidad Punta
Morro. Esta carpeta reúne simulación y Pygame (Persona 1), datos e IA
(Persona 2) y rutas (Persona 3). Puede instalarse por separado: no depende
de `Chagoya/`.

El escenario activo de `main.py` usa **480 × 300 celdas, 1.879 alumnos,
55 edificios, 11 laboratorios de mayor riesgo y ocho zonas de reunión**.
El escenario anterior 160 × 100 sigue disponible con `python main.py --legacy`.

## Sexta fase conservada: referencia anterior

Estado: **PARTIALLY READY**. En 16 escenarios pareados, las medias
Traditional → Intelligent fueron incapacitados **26.06 → 14.56**, dosis
**93.41 → 47.52**, sin asignación **213.81 → 24.75** y replanes
**2717.56 → 1498.88**. Los contactos con fuego empeoraron **2.50 → 2.94**;
las llegadas a reunión bajaron **877.38 → 770.94**. El SafetyScore subió
**98.87 → 99.46**, pero eso no justifica la regresión de fuego.

La medición aislada de 240 turnos dio **0.6483 s/turno**, frente a **1.1769**
al reproducir quinta fase (referencia histórica: 1.2468). Se cumplió el objetivo
<=0.8; Traditional actual midió 0.3921. Intelligent sigue siendo más costoso
que Traditional. El fuego/humo final tuvo el mismo hash que la referencia.
En ese episodio comparable, los contactos también subieron 0→1 e incapacitados
10→13. El problema pendiente principal es el encierro interior, especialmente
E16 con un único grupo de salida; no se añadieron puertas ni se relajó el bloqueo.

`python main.py` abre INTELIGENTE. Se conservan las 480×300 celdas, 1.879 alumnos,
el mapa, puertas, reuniones, física, sensores y modelos anteriores.
No hay dependencias nuevas. La evaluación final de esta fase está en
`SIXTH_FUNCTIONAL_CHANGES_FEEDBACK.md`.

- Fuego: `fire_eta`, `smoke_eta` y `hazard_eta` separados. Se revisan **todos**
  los puntos de una ruta para fuego; no hay excepción de prefijo para fuego.
  Un watchdog vuelve a comprobar la próxima celda antes de cada paso exterior.
- Dosis: `toxic_dose_eta` estima presupuesto personal restante / tasa prevista.
  `personal_hazard_eta = min(environmental_hazard_eta, toxic_dose_eta)`.
  Son turnos y dosis didácticos, sin interpretación médica.
- Estabilidad: invalidaciones duras inmediatas; cambios menores respetan cooldown
  y solo sustituyen una ruta segura si mejoran claramente coste o riesgo.
- Rendimiento: guías multi-source compartidas por reunión y snapshot **exacto**
  de costes/bloqueos. A* ponderado sigue siendo fallback. Cada plan pasa el
  contrato y validación temporal; compartir plan no comparte posición.
- Reuniones: ocupación, reservas en tránsito, tasa de llegada aproximada y capacidad
  de entrada estimada desde bordes transitables. Seguridad se filtra antes de puntuar.
- Diagnóstico: causas individuales de falta de ruta y progreso/historial de escapes.
  Después de A, clic sobre un alumno muestra su última decisión. **D** alterna
  un overlay de riesgo, desactivado inicialmente. El foco por clic antes de A
  y el texto de tortugas se conservan.

Configuración adicional: `fire_safety`, `personal_safety`, `escape_policy`,
`route_stability`, `routing_optimization`, `safety_score`, y extensiones de
`route_scheduling` / `meeting_assignment` en `data/functional_scenario.json`.
El presupuesto de dosis del planificador es 2.75, igual al umbral físico actual;
cambiar ese presupuesto no cambia el umbral de `ExposureTracker`.

Desde `DisasterCommandCenter/`:

```powershell
python main.py
python main.py --evacuation-mode traditional
python main.py --legacy
python tests/test_sixth_functional_changes.py
python tools/run_tests.py
python tools/profile_evacuation.py --turns 240 --profile
python tools/compare_evacuation_modes_v2.py --turns 160 --workers 3
```

El benchmark ejecuta **16 escenarios × 2 modos**, con inputs físicos idénticos
y hashes de fuego/humo por turno. Incluye E15/E16, vegetación, viento brusco,
dos reuniones amenazadas y una puerta principal incendiada. Escribe
`reports/evacuation_comparison_v2/summary.json`, `summary.csv`, `per_scenario.csv`
y checkpoints. `--resume` verifica código, configuración, **todos los JSON de
datos** y artefacto del predictor. Los tiempos concurrentes del lote no sustituyen
la medición aislada de 240 turnos. Los informes son generados, ignorados por Git.

`SafetyScore` es un resumen 0–100 cuyos pesos se fijaron antes del benchmark:
40 incapacitación, 30 contacto con fuego, 15 dosis, 10 espera insegura y 5 destino
inseguro; cada término usa una fracción normalizada y acotada. Se conserva cada
métrica original. Una puntuación alta **no certifica seguridad** ni oculta casos
individuales. Véase la fórmula completa en el feedback.

La reproducción sigue en x1.75 nominal. Esta fase reduce cálculo; no cambia
fuego, humo ni desplazamiento por turno. Una ETA es una heurística local,
no una garantía contra brasas, ocupación, encierro o cambios futuros de viento.

## Quinta fase: referencia histórica anterior a la sexta

Los siguientes números corresponden exclusivamente al lote archivado de quinta
fase. Los comandos antiguos invocan el código actual; para la nueva comparación
se debe usar la herramienta `compare_evacuation_modes_v2.py` indicada arriba.

Estado: **PARTIALLY READY**. Diez escenarios pareados (160 turnos por modo)
dieron medias Traditional → Intelligent de incapacitados **43.7 → 17.5**,
dosis de humo **155.17 → 59.43** y espera insegura **2123 → 1022.4 persona-turnos**.
Intelligent redujo dosis/espera en los diez casos e incapacitados en ocho, con dos
empates. Los contactos directos con fuego subieron **2.5 → 3.3** y el coste medido
por turno pasó de **0.445 s a 1.247 s** frente a la cuarta fase restaurada.
Esos dos indicadores impiden clasificar esta entrega como READY.

`python main.py` inicia **INTELIGENTE**. Para comparar visualmente:

```powershell
python main.py --evacuation-mode traditional
python main.py --evacuation-mode intelligent
```

Estos modos son políticas de evacuación; `--modo-original` sigue seleccionando
el administrador de personas y `--legacy` conserva el escenario anterior.

El campo compartido `HazardArrivalField` estima turnos hasta peligro a partir
de fuego/humo observados y viento actual/predicho. Es una heurística didáctica
local con horizonte de 60 turnos, **no una predicción física calibrada**.
Infinito significa fuera del horizonte, no seguridad permanente.

La política compara `safety_margin = hazard_eta - evacuation_eta`, prioriza
esperas inseguras, incorpora antigüedad sin límite y valida muestras temporales
de cada ruta antes de aceptarla. Conserva destinos seguros; una amenaza futura
puede invalidarlos incluso durante cooldown. Si no hay ruta completa y esperar
es peligroso, busca un `SafeIntermediateGoal` local alcanzable. El gateway
existente ejecuta los pasos: máximo una celda por alumno por turno.

Se mantienen A* ponderado, congestión, población, ocho reuniones y toda la física
de la tercera fase. No se añadieron dependencias ni se reentrenó Ridge/Persona 2.
La telemetría de viento sigue separada del contrato de detección de incendios.

En **TRADITIONAL** se fija la reunión más cercana a una salida al activar alarma.
Se usa distancia/congestión sin coste previsto; la ruta se mantiene, salvo
imposibilidad por peligro actual. Las salidas evitan bloqueos actuales. No se
reasigna por viento ni por pronóstico. Ambos modos tienen presupuesto base 24
búsquedas A* reales, ampliable a 40 cuando hay al menos 48 solicitudes pendientes.
Las solicitudes y escapes también están acotados. Una comprobación de componentes
del mismo grafo omite búsquedas imposibles sin alterar rutas exitosas. Las mediciones
predictivas de Traditional son solo del observador comparativo.

Desde esta carpeta, comparación reproducible sin ventana:

```powershell
python tools/compare_evacuation_modes.py --scenarios 10 --turns 160
python tools/run_functional_episode.py --turns 240 --evacuation-mode intelligent --output reports/quinta_fase/episode.json
python tests/test_fifth_functional_changes.py
```

Resultados: `reports/evacuation_comparison/summary.json`, `summary.csv` y archivos
por escenario/modo. `--resume` solo reutiliza resultados con igual configuración,
fuentes e inputs y presupone que los assets del mapa y el modelo no cambiaron.
Si modificas datos derivados o el artefacto de viento, ejecuta sin `--resume`.
Se verifica igualdad exacta de la trayectoria física por turno.
Las métricas de tiempo hasta reunión solo incluyen personas que llegaron;
quienes no llegaron están censurados y se informan en los conteos.
`confirmed_forecast_departures` cuenta salidas motivadas por pronóstico cuya
celda estaba bajo el umbral al salir y realmente se volvió peligrosa después: es un indicador
observado, **no una lesión evitada demostrada mediante contrafactual**.

Configuración nueva en `data/functional_scenario.json`: `hazard_arrival`,
`intelligent_evacuation`, `route_safety`, `meeting_assignment`, `route_scheduling`
y `comparison`. La reproducción permanece a x1.75; ninguna ETA cambia la física.
El HUD muestra modo, espera insegura, replanes, reasignaciones preventivas,
reuniones evitadas y método de viento. Los avisos tienen cooldown.

Consulta `FIFTH_FUNCTIONAL_CHANGES_FEEDBACK.md` para resultados medidos,
limitaciones, pruebas y estado de entrega. Los datos siguen siendo sintéticos.

## Cuarta fase conservada: riesgo espacial y predicción de viento

Las rutas conservan distancia y congestión y añaden costes compartidos por
proximidad al fuego, humo actual, vegetación ardiendo, laboratorios críticos y
corredor probable de humo. No se prohíbe acercarse temporalmente al peligro si
es necesario para salir; fuego y humo crítico siguen bloqueando el siguiente paso.
Las salidas interiores también ponderan riesgo exterior y conservan puertas alternas.

Las reuniones muestran **SAFE, CAUTION, AVOID o CLOSED**. AVOID deja de recibir
alumnos nuevos antes de alcanzar el umbral de cierre actual. Hay histéresis,
recuperación y cooldown; el peligro actual y la amenaza prevista fuerte prevalecen.
Recalcular por congestión conserva un destino que siga siendo seguro y alcanzable.
Los recálculos mantienen presupuesto de 24 intentos por turno y prioridad de laboratorios.

Los sensores virtuales exteriores **S-EXT-01 y S-EXT-02** miden el vector global
de viento mediante un contrato separado `wind_observation/1.0`, sin cambiar las
columnas de Persona 2. Se observa al iniciar y una vez por turno; pausa no duplica.
`E` exporta los archivos térmicos originales y, aparte, `wind_observations.jsonl`
y `wind_manifest.json`, con coordenadas finas y `data_source=synthetic_simulation`.

El pipeline independiente `src/wind_prediction/` usa cuatro lags de u/v/velocidad
y deltas para predecir el siguiente u/v. Ridge se entrena fuera de la aplicación,
con separación por secuencias. El main carga `data/wind_prediction/model.json`.
Ante historial insuficiente, viento constante, archivo ausente o error, usa
persistencia. **La predicción no modifica el viento real.** Solo anticipa riesgo.
En el HUD, `[R]` indica Ridge y `[P]` persistencia.

Evaluación sintética de test: RMSE u/v de persistencia **0.08458**, Ridge puro
**0.08406**, predictor seleccionado con fallback **0.08385**. Persistencia gana
en error angular y de velocidad. No se afirma una mejora general ni capacidad
meteorológica real; son patrones de viento virtual, no clima de Ensenada.

La reproducción predeterminada es **1.75×**: intervalo objetivo de 228.6 ms,
frente a 400 ms. No cambia fuego, humo ni desplazamiento por turno. Máximo una
celda por alumno y turno; FPS objetivo sigue en 45. El rendimiento del equipo
limita la velocidad efectiva. Las APIs para futuros sliders son
`scene.configure_wind(direction=..., speed=...)` y
`app.set_simulation_speed(multiplier)`; todavía no hay sliders.

Configuración: `risk_routing`, `meeting_area_policy`, `wind_telemetry`,
`wind_prediction` y `simulation_playback` en `data/functional_scenario.json`.
NumPy, SciPy y scikit-learn ya estaban incluidos; no hay dependencias nuevas.

~~~powershell
python main.py
python tests/test_fourth_functional_changes.py
python tools/train_wind_predictor.py
python tools/run_functional_episode.py --turns 240 --output reports/cuarta_fase/episode.json
python tools/run_functional_episode.py --turns 120 --controlled-wind --output reports/cuarta_fase/episode_varied_wind.json
~~~

El entrenamiento es explícito; `main.py` nunca reentrena. El modelo y dataset
sintético reproducible están en `data/wind_prediction/`, separados del target
`fire_within_2_cells`, que sigue sin entrar en features.
Véase [FOURTH_FUNCTIONAL_CHANGES_FEEDBACK.md](FOURTH_FUNCTIONAL_CHANGES_FEEDBACK.md).

## Parámetros físicos conservados de la tercera fase

El escenario activo usa parámetros propios en `data/functional_scenario.json`;
los motores y datos legacy conservan sus valores anteriores.

| Parámetro por turno | Activo | Anterior |
| --- | ---: | ---: |
| Propagación base en edificio normal | 0.075 | 0.57 |
| Propagación base en vegetación | 0.060 | 0.34 |
| Multiplicador de laboratorio inflamable | 1.6 | 1.0 |
| Coeficiente de influencia del viento sobre fuego | 0.6 | 1.2 |
| Duración de combustión edificio / vegetación | 18 / 14 | 7 / 4 |
| Disipación de humo | 0.008 (0.8%) | 0.08 (8%) |

Los laboratorios reutilizan `building_properties.json`: la probabilidad aumenta
si origen o destino pertenece a un laboratorio con materiales inflamables.
No hay explosiones. El humo conserva emisión, difusión, transporte por viento y
límite 1.0; se disipa lentamente. Los umbrales siguen siendo 0.30 para reuniones
y 0.65 para rutas. Un turno no representa segundos ni metros reales.

Las brasas están activas: con viento >= 0.4, cada foco anterior propone una
brasa con probabilidad `0.004 × intensidad`, a 3–12 celdas finas y en un cono
a favor del viento. Como máximo dos igniciones secundarias por turno.
Solo encienden combustible válido, nunca roads, andadores ni reuniones.
`fire_behavior.spotting_enabled=false` las desactiva. La semilla hace el
resultado reproducible; no es una predicción de incendios reales.

La máscara vegetal determinista ocupa **4,119 celdas fuente = 37,071 finas
añadidas**; con los jardines originales hay **38,538 celdas finas de vegetación
combustible**. Se conservan carreteras, edificios, reuniones y conexiones
peatonales entre todas las puertas y reuniones. No es un levantamiento botánico.

La política de salidas usa áreas efectivas: P75=67 y P90=124.2 celdas fuente.
Los edificios con área >= P75 tienen dos salidas; los de área >= P90, tres.
Se conservan todas las puertas anteriores, incluido E31 norte/sur, y se añaden
19 salidas fuente en 13 edificios. Total: 75 salidas fuente, 225 pares finos.
El controlador interior elige puertas seguras y recalcula su campo de distancias
al cambiar fuego, humo peligroso o bloqueos; reutiliza el mismo motor de movimiento.

Para regenerar datos y medir un episodio real desde esta carpeta:

~~~powershell
python tools/build_functional_scenario.py
python tools/run_functional_episode.py --turns 240 --compare
python tests/test_third_functional_changes.py
~~~

El episodio escribe métricas en `reports/tercera_fase/episode.json`; admite
`--ignition X Y` en coordenadas finas, sin introducir focos adicionales.
Los alumnos pueden quedar atrapados por riesgo u ocupación: el informe conserva
esas limitaciones y no supone que todos hayan llegado a una zona segura.
Véase [THIRD_FUNCTIONAL_CHANGES_FEEDBACK.md](THIRD_FUNCTIONAL_CHANGES_FEEDBACK.md).

## Controles conservados de la segunda fase

- Las orientaciones están definidas en `data/functional_scenario.json`, no solo
  en el JSON derivado: E19, ambos sectores de E60, E8, E6, E4 y E57 al sur;
  E7 al norte; E32 y E28 al oeste; E55 al sur; E18 y E14 al este; E31 al norte
  y al sur. Estos 168 pares originales siguen incluidos entre los 225 actuales.
- **Antes de A**, un clic izquierdo sobre un edificio o vegetación combustible
  selecciona el foco. Una cruz naranja marca la celda elegida. Se respeta zoom
  y desplazamiento de cámara. Caminos, reuniones y fuera del mapa no son focos válidos.
- Al pulsar **A**, comienza en esa celda. Sin selección usa el foco anterior de
  E30: fuente (78,55), fino (235,166). Después de iniciar, el clic no añade focos;
  aún permite inspeccionar sensores. R limpia la selección.
- Los cuatro parches iniciales se amplían mediante la máscara distribuida
  de la tercera fase. Se excluyen road, edificios, reuniones, puertas y sensores.
  El registro reproducible está en
  `data/functional/vegetation.json`. El terreno fuera del campus no se vuelve
  automáticamente combustible.
- El fuego vegetal genera humo con los motores existentes. Routing y cruce de
  puertas evitan fuego, humo >= 0.65 y un margen de una celda fina de camino junto
  a vegetación ardiendo. El mismo MeetingRouter retira/recalcula rutas y destinos.
- El HUD inferior muestra: «Ninguna tortuga saldrá lastimada durante esta simulación.»

Consulta [SECOND_FUNCTIONAL_CHANGES_FEEDBACK.md](SECOND_FUNCTIONAL_CHANGES_FEEDBACK.md)
para coordenadas de puertas, criterios geométricos, pruebas y limitaciones.
El modo `--legacy` conserva los datos y controles anteriores, incluido su
comportamiento histórico del clic.

## Escenario funcional activo

- Cada celda fuente se subdivide en 3 × 3 celdas reales: movimiento, ocupación,
  fuego y humo se calculan en el grid fino. Se conserva la geometría del campus.
- Población de 30–50 por edificio según su área efectiva. El edificio más
  pequeño dispone de 54 subceldas, suficiente para 30 personas sin solaparlas.
- Laboratorios: E19, E16, E15, E8, E6, E7, E9, E45, E35, E36 y E51.
  Se muestran en violeta. Ante fuego a seis celdas fuente se activa prioridad
  crítica; los normales alertan a dos celdas. La prioridad ordena movimiento
  interior y el presupuesto de cálculo de rutas exteriores.
- R1–R8 son destinos activos sobre espacios transitables. Se descartan como destino
  ante fuego, humo máximo >= 0.30, deshabilitación o falta de plazas libres. Se reserva una
  celda distinta por alumno. Si un destino se compromete, se retira su ruta y se
  intenta otra zona segura y alcanzable, incluso después de haber llegado.
- Las rutas exteriores usan A* ponderado/congestión de Persona 3 y son seguidas
  por el gateway de Persona 1. El controlador interior no mueve a los exteriores.
- El humo oscurece según concentración y se desplaza por el viento. Una flecha
  indica hacia dónde sopla. `V` cambia dirección y `[`/`]` velocidad normalizada
  0–1; no son m/s. Hay historial y pronóstico simple por persistencia, sin sliders.

La configuración editable está en `data/functional_scenario.json` y los archivos
derivados en `data/functional/`. Para regenerar mapa, accesos, población y
propiedades tras cambiar parámetros:

~~~powershell
python tools/build_functional_scenario.py
~~~

No se editan `data/campus.json`, accesos, ocupación de ejemplo ni sensores
originales. Las lecturas exportadas conservan el contrato 160 × 100 mediante
proyección explícita: humo máximo y presencia de fuego por bloque 3 × 3.
Las coordenadas visibles del sensor son finas; sus coordenadas exportadas son
las originales. Los metadatos de exportación describen esa diferencia.
La IA no dirige rutas ni se reajusta automáticamente con el nuevo escenario.

Las zonas de reunión son aproximaciones del suelo abierto del plano, que no
identifica estacionamientos como categoría. Se documentan sus coordenadas,
políticas y limitaciones en
[FUNCTIONAL_CHANGES_FEEDBACK.md](FUNCTIONAL_CHANGES_FEEDBACK.md).

**Los sensores y datasets son simulados.** Los turnos no son segundos reales.
El predictor es experimental. Salir de un edificio o llegar a un destino
de prueba no acredita una zona segura.

## Instalación desde cero

Se recomienda **Python 3.13 de 64 bits**; verificado con Python 3.13.7 en
Windows. Pygame necesita pantalla para el uso interactivo.

Desde la raíz del repositorio, en PowerShell:

~~~powershell
cd DisasterCommandCenter
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python main.py
~~~

Si PowerShell impide activar el entorno, usa sus ejecutables directamente:

~~~powershell
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe main.py
~~~

En Linux/macOS se activa con `source .venv/bin/activate`.
No se distribuye ni versiona un venv. Si ya existe uno en la raíz del
repositorio, desde esta carpeta puedes usar `..\.venv\Scripts\python.exe`.

`requirements.txt` instala Pygame e incluye `requirements-persona2-ml.txt`
para disponer de análisis, modelos e inferencia. Se conservan sus versiones
reproducibles. Routing y el ejecutor de tests usan la biblioteca estándar.
PostgreSQL y su driver son opcionales.

## Ejecutar y controles

~~~powershell
python main.py
# Usar el administrador original solo en esta sesión:
python main.py --modo-original
~~~

`main.py` carga el escenario detallado y reutiliza la ventana existente.
Si no hay configuración local, se usa el administrador original.
`python main.py --legacy` delega en `main_unificado_14_4_4.py` y conserva
el escenario anterior de 100 personas. Ambos admiten `--smoke-test`.

| Control | Acción |
| --- | --- |
| A | Iniciar alarma y evacuación |
| Espacio | Pausar/reanudar |
| . | Avanzar un turno mientras está pausado |
| R | Reiniciar; después pulsa A |
| T | Cambiar escenario normal/emergencia antes de A |
| M | Cambiar administrador antes de A, sujeto a la autorización local existente |
| V | Cambiar dirección del viento |
| [ / ] | Reducir/aumentar intensidad del viento |
| + / - | Aumentar/reducir velocidad de los turnos |
| H | Mostrar/ocultar humo |
| S / Tab | Mostrar sensores / seleccionar el siguiente |
| E | Exportar lecturas CSV, JSONL y manifiesto |
| F | Encuadrar campus |
| N / G / P | Etiquetas / cuadrícula / accesos |
| Rueda del ratón | Zoom |
| Arrastrar con botón derecho | Desplazar mapa |
| Clic izquierdo | Elegir foco antes de A; después seleccionar alumno |
| Esc | Cerrar |

La exportación queda en `exports/sensores_paso_14_4_4/`.
El escenario normal no inventa lecturas de fuego/humo.
El administrador `optimizado` de Persona 1 usa un índice de ocupación;
**no activa EvacuationOptimizer de Persona 3**.

## Estructura

~~~text
DisasterCommandCenter/
├── main.py                       # Entrada estable
├── README.md
├── FUNCTIONAL_CHANGES_FEEDBACK.md # Cambios activos posteriores
├── SECOND_FUNCTIONAL_CHANGES_FEEDBACK.md # Segunda fase funcional
├── THIRD_FUNCTIONAL_CHANGES_FEEDBACK.md # Física de tercera fase conservada
├── FOURTH_FUNCTIONAL_CHANGES_FEEDBACK.md # Cuarta fase conservada
├── FIFTH_FUNCTIONAL_CHANGES_FEEDBACK.md  # Evaluación y pendientes de quinta fase
├── requirements.txt              # Pygame + IA
├── requirements-persona2-ml.txt
├── requirements-persona2-db.txt   # PostgreSQL opcional
├── .env.example
├── data/                         # Campus, accesos, ocupación y sensores
├── src/
│   ├── simulation/               # Motores de Persona 1
│   ├── dcc_app/                  # Escenas y Pygame
│   ├── integration/              # Contratos y gateways
│   ├── persona2/                 # Datos, IA y PostgreSQL
│   ├── routing/                  # Persona 3
│   └── wind_prediction/          # Predictor independiente de viento virtual
├── tests/                        # Nuevas regresiones de consolidación
├── test_*.py                     # Pruebas históricas conservadas
├── tools/                        # Ejecutor común y verificación DB
├── docs/                         # Arquitectura y documentación histórica
├── PERSONA2.md
└── main_unificado_14_4_4.py       # Lanzador compatible
~~~

Se conservaron scripts numerados y tests en la raíz porque usan `__file__`,
imports locales y verificaciones de archivos concretos. El ejecutor común
los reúne sin reescribirlos. `reports/`, `exports/`, cachés y entornos son
locales e ignorados por Git.

## Módulos y conexiones reales

**Persona 1:** mapa fuente de 160 × 100, motores, personas, evacuación,
fuego, humo, viento, 12 sensores, exportación y ventana gráfica. El escenario
funcional los reutiliza sobre la cuadrícula derivada de 480 × 300.

**Persona 2:** validación CSV/JSONL/manifiesto del contrato 1.0, dataset,
EDA, baseline, comparación, inferencia sustituible y repositorio PostgreSQL.
`X = temperature_c, smoke_index, alarm`; `y = fire_within_2_cells` permanece
separado. IDs, ubicación y turno son contexto fuera de X. El gateway elimina
el target antes de llamar al predictor.

**Persona 3:** CampusGraph, A*, A* ponderado, congestión, prioridades,
replanning individual/múltiple, RoutingController y EvacuationOptimizer.
Calcula rutas que el gateway de Persona 1 valida y sigue para personas
exteriores.

En `python main.py`, Pygame ejecuta la escena detallada: motores, sensores,
prioridades de laboratorios y rutas exteriores hacia zonas de reunión,
incluida reasignación por humo y riesgo previsto. Activa el predictor independiente
de viento; **no activa el detector de incendio de Persona 2 ni PostgreSQL.**
`--legacy` conserva la escena anterior sin rutas de reunión automáticas.

La demostración existente de Persona 2 se ejecuta en esta misma carpeta:

~~~powershell
python demo_persona2_integracion.py --output-dir reports/persona2_demo
~~~

Genera un ejemplo sintético, ajusta el baseline existente solo con su
partición de entrenamiento y consume una escena mediante
SensorPredictionAdapter. Produce 432 predicciones de 12 sensores en
36 turnos y un informe JSON. Comparte escenario con el entrenamiento:
es una demostración funcional, no una evaluación independiente de calidad.

Persona 3 se comprueba contra el gateway real mediante:

~~~powershell
python test_integration_persona1.py
python tests/test_consolidation.py
~~~

Las rutas del escenario nuevo usan concentraciones y fuego del simulador,
no las predicciones booleanas de IA. Los destinos están configurados
explícitamente. Véase [arquitectura](docs/ARCHITECTURE.md).

## Pruebas

~~~powershell
python tools/run_tests.py
~~~

Descubre los scripts `test_*.py` de la raíz y de `tests/`, los ejecuta
por separado en una copia temporal con SDL dummy y guarda salidas y conteos
en `reports/integration_tests/`. Continúa tras un fallo y devuelve código
distinto de cero si alguna prueba falla. Las omisiones de PostgreSQL
aparecen explícitamente; no prueban funcionamiento de DB.

Prueba rápida del punto de entrada sin pantalla:

~~~powershell
$env:SDL_VIDEODRIVER = "dummy"
$env:SDL_AUDIODRIVER = "dummy"
python main.py --modo-original --smoke-test
Remove-Item Env:SDL_VIDEODRIVER
Remove-Item Env:SDL_AUDIODRIVER
~~~

Abre tres fotogramas y termina; no ejecuta una evacuación completa.
Retira SDL dummy antes de abrir la ventana interactiva.

## PostgreSQL opcional

No hace falta servidor DB para Pygame, dataset, EDA o inferencia.
Para persistencia y sus tests:

~~~powershell
python -m pip install -r requirements-persona2-db.txt
~~~

Para pruebas completas, configura el directorio que contiene `initdb`
y `pg_ctl` de tu instalación PostgreSQL:

~~~powershell
$env:DCC_POSTGRES_BIN = "C:\Program Files\PostgreSQL\18\bin"
python tools/run_tests.py --require-db
python tools/verify_persona2.py
~~~

Se verificó PostgreSQL 18.4. El helper crea un clúster temporal local con
contraseña aleatoria, lo detiene y elimina al terminar. En Unix ejecuta
`initdb` con un usuario sin privilegios root.
Como alternativa, configura `DCC_TEST_DATABASE_URL` hacia una base de
pruebas con permiso para crear esquemas. `--require-db` falla ante falta de
configuración u omisiones.

Para conservar resultados en un servidor propio, crea primero la base y
configura una conexión con permiso para crear el esquema `persona2`:

~~~powershell
$env:DCC_DATABASE_URL = "postgresql://usuario:contrasena@127.0.0.1:5432/disaster_command_center"
python demo_persona2_integracion.py --persist
~~~

`.env.example` documenta las variables. Los scripts **no cargan .env
automáticamente**. La persistencia es explícita y ocurre fuera del bucle
gráfico mediante un repositorio independiente.

El estado de la primera fase está en [FUNCTIONAL_CHANGES_FEEDBACK.md](FUNCTIONAL_CHANGES_FEEDBACK.md)
y la segunda fase en [SECOND_FUNCTIONAL_CHANGES_FEEDBACK.md](SECOND_FUNCTIONAL_CHANGES_FEEDBACK.md).
La tercera fase está en [THIRD_FUNCTIONAL_CHANGES_FEEDBACK.md](THIRD_FUNCTIONAL_CHANGES_FEEDBACK.md).
El histórico de cuarta fase está en [FOURTH_FUNCTIONAL_CHANGES_FEEDBACK.md](FOURTH_FUNCTIONAL_CHANGES_FEEDBACK.md).
El estado activo está en [SEVENTH_FUNCTIONAL_CHANGES_FEEDBACK.md](SEVENTH_FUNCTIONAL_CHANGES_FEEDBACK.md).
El histórico INTEGRATION_FEEDBACK.md no está presente en esta copia;
la arquitectura está documentada en [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).
El README previo está en
[docs/PERSONA1_LEGACY.md](docs/PERSONA1_LEGACY.md); el desarrollo de Persona 2
en [PERSONA2.md](PERSONA2.md).
