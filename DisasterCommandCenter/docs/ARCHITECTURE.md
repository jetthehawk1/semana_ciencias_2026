# Arquitectura de la base consolidada

## Escenario funcional posterior, activo desde main.py

La auditoría estructural que sigue describe la base anterior. Actualmente:

```text
main.py -> FunctionalDisasterApp -> FunctionalScene
  -> FunctionalSimulation (grid 480x300, poblacion calculada)
  -> motores de fuego/humo/viento + ExposureTracker
  -> BuildingRisk -> EvacuationPriority
  -> MeetingRouter -> A* ponderado/congestion de Persona 3
  -> ExternalRouteFollower: movimiento exterior
  -> HazardEvacuationController(manage_exterior=False): movimiento interior
  -> sensores proyectados a grid fuente / UI / exportacion
```

El exterior se mueve antes que el interior: quien cruza una puerta espera al
siguiente turno para su ruta exterior. Las zonas se reevalúan por humo en cada
turno. Solo el gateway ejecuta movimiento exterior. WindHistory ofrece estado,
historial limitado y pronóstico de persistencia, sin Pygame.

`main.py --legacy` conserva el flujo estructural descrito abajo. La IA y DB
siguen siendo servicios separados; no hay predicciones de IA convertidas en
bloqueos. Las coordenadas finas no se mezclan con el contrato de sensores.
Véase [feedback funcional](../FUNCTIONAL_CHANGES_FEEDBACK.md).

La integración es estructural: reúne código existente y comprueba los
gateways sin cambiar el comportamiento de la simulación interactiva.

## Auditoría inicial

- Rama activa: `persona1-simulacion`, commit `941b0bd`.
- `persona2-datos-ia` también apuntaba a `941b0bd`; el código de Persona 2
  estaba presente como archivos sin commit.
- `persona3-rutas` y su remoto apuntaban a `e040597`, descendiente de Persona 1:
  añadían 12 archivos de routing y 10 tests, sin cambiar motores existentes.
- `main`/`origin/main`: `97598a2`, implementación Chagoya.
- Había cambios locales de Chagoya, incluidos binarios de caché versionados.
  Se conservaron sus bytes y fuentes.
- Chagoya requiere CO, intensidad/distancia del fuego, ocupación y estado
  de zonas; esos campos no existen en el contrato principal de sensores.
  No se copió ese pipeline ni se inventaron datos.
- Los scripts numerados incluyen dependencias activas del selector de
  administrador, índice espacial, generadores y tests. Se conservaron.

## Flujo gráfico activo

~~~text
main.py
  -> main_unificado_14_4_4.main
  -> ModeSensorDisasterApp (Pygame)
  -> ModeSensorScene
  -> centro normal/emergencia de Persona 1
  -> evacuación base, fuego/humo/viento y exposición
  -> VirtualSensorNetwork: 12 lecturas por turno de emergencia
  -> UI de sensores / export_sensor_dataset (tecla E)
~~~

No instancia predictor, repositorio PostgreSQL ni optimizador de rutas.
El modo `optimizado` de Persona 1 usa un índice espacial de ocupación y
es independiente de `routing.EvacuationOptimizer`.

## Flujo disponible de Persona 2

~~~text
CSV + JSONL + manifiesto
  -> ingestion: contrato existente + configuración de sensores
  -> dataset: X (temperatura, humo, alarma), y y contexto separados
  -> EDA / baseline / comparación
  -> PredictionService

ModeSensorScene.current_readings
  -> SensorPredictionAdapter / predict_sensor_readings
  -> retira fire_within_2_cells
  -> predictor sustituible
  -> predicted_fire_within_2_cells
  -> informe JSON
  -> PostgresRepository, solo si se solicita persistencia
~~~

Se conserva el árbol experimental: profundidad máxima 3, mínimo 2 muestras
por hoja, clases balanceadas y random_state 2026. La demostración usa solo
la partición de entrenamiento de P2.4. No se interpreta su salida como CO,
riesgo médico o nivel de prioridad. La etiqueta indica fuego activo a
distancia Manhattan <= 2 en el mismo turno.

## Flujo disponible de Persona 3

~~~text
campus -> CampusGraph
manager + destinos explícitos + celdas bloqueadas
  -> build_route_request
  -> A* / calculate_route_response
     o EvacuationOptimizer (congestión + prioridades + A* ponderado)
  -> respuesta de ruta, contrato 1.0
  -> ExternalRouteFollower.set_request / submit_route
  -> ExternalRouteFollower.step -> manager.move_person

ruta bloqueada + solicitud actualizada
  -> DynamicReplanner / MultiPersonReplanner / RoutingController
  -> nueva respuesta -> mismo gateway
~~~

El gateway admite personas exteriores, no calcula objetivos y no marca
`a_salvo` por llegar a un destino. Persona 3 calcula; Persona 1 valida y
sigue rutas. Los tests usan destinos explícitos de prueba.
El alias `CampusGraph.neighbors()` permite usar el A* ponderado existente
sin modificar costes ni el método público previo `get_neighbors()`.

## Límites conservados

No hay política acordada que convierta predicciones de sensores en riesgo
de todas las celdas, prioridades personales o destinos seguros.
Por ello no se implementó IA -> routing -> movimiento en Pygame.
Activarlo exige un cambio funcional posterior: destinos configurados,
sincronización de turnos y exclusión de doble movimiento.

Los replanners pasan los escenarios existentes; no garantizan resolver
todos los conflictos de múltiples agentes. La congestión añade costes
espaciales, no reservas temporales. Las prioridades ordenan el cálculo,
no necesariamente el movimiento del gateway. El optimizador no hace
una planificación global conjunta.

## Pruebas y compatibilidad

Tests existentes en la raíz para preservar imports y rutas; los nuevos
están en `tests/`. El ejecutor común usa procesos separados en una copia
temporal de esta carpeta sin copiar Chagoya ni venv. PostgreSQL es opcional
y las omisiones se registran. El README anterior se archivó y no se
eliminaron lanzadores ni scripts de compatibilidad.
