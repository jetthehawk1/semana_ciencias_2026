"""Build the handoff document from completed measurements, not guessed values."""
from pathlib import Path
import json,hashlib,pstats

R=Path(__file__).resolve().parents[2]
OUT=R/'reports/sexta_fase'
bench=json.loads((R/'reports/evacuation_comparison_v2/summary.json').read_text(encoding='utf-8'))
assert bench['complete'] and len(bench['scenarios'])==16
after=json.loads((OUT/'performance_after.json').read_text())
before=json.loads((OUT/'baseline_240.json').read_text())
tests=json.loads((OUT/'tests_final/results.json').read_text())['summary']
config=json.loads((R/'data/functional_scenario.json').read_text())
old=json.loads((R/'reports/evacuation_comparison/summary.json').read_text())
cases=bench['scenarios'];a=bench['aggregate'];T=a['traditional'];I=a['intelligent']
primary_case=next(c for c in cases if c['scenario_id']=='S15')
def table(headers,rows):
    return '\n'.join(['| '+' | '.join(headers)+' |','| '+' | '.join('---' for _ in headers)+' |']+
        ['| '+' | '.join(str(x) for x in row)+' |' for row in rows])
def fmt(n):return f'{n:.4f}' if isinstance(n,float) else str(n)
keys=['safe_meeting_arrivals','people_exposed_smoke','accumulated_smoke_dose','people_close_to_fire',
    'fire_contacts','incapacitated','unsafe_waiting_person_turns','unassigned','routes_recalculated','distance_traveled',
    'destination_became_unsafe_before_arrival','temporary_goals','SafetyScore','runtime_seconds']
results=table(['Métrica (media de 16)','Traditional','Intelligent'],[(k,fmt(T[k]['mean']),fmt(I[k]['mean'])) for k in keys])
scenario_rows=table(['Caso / categoría','Foco / seed','Fuego T/I','Incapacitados T/I','Sin ruta T/I','SafetyScore T/I'],[
    (c['scenario_id']+' / '+c['category'],str(c['ignition'])+' / '+str(c['seed']),
     str(c['traditional']['metrics']['fire_contacts'])+'/'+str(c['intelligent']['metrics']['fire_contacts']),
     str(c['traditional']['metrics']['incapacitated'])+'/'+str(c['intelligent']['metrics']['incapacitated']),
     str(c['traditional']['metrics']['unassigned'])+'/'+str(c['intelligent']['metrics']['unassigned']),
     fmt(c['traditional']['metrics']['SafetyScore'])+'/'+fmt(c['intelligent']['metrics']['SafetyScore'])) for c in cases])
matched=[]
for c in cases[:10]:
    previous=next(v for v in old['scenarios'] if v['scenario_id']==c['scenario_id'])
    assert previous['intelligent']['physical_trajectory']==c['intelligent']['physical_trajectory']
    matched.append((previous,c))
def matched_means(key):
    return (sum(p['intelligent']['metrics'][key] for p,c in matched)/10,
            sum(c['intelligent']['metrics'][key] for p,c in matched)/10)
def delta_text(key):
    x,y=matched_means(key);return f'{x:.4f} → {y:.4f} (mismos diez inputs y trayectoria física; cambio {y-x:+.4f}).'
def prof(path):
    stats=pstats.Stats(str(path));rows=[]
    categories=[('A*','weighted_astar.py','weighted_astar'),('Guías compartidas','meeting_flow.py','route'),
        ('Hazard ETA','hazard_arrival.py','update'),('Campo de riesgo','dynamic_risk.py','update'),
        ('Evaluación de reuniones','meeting_areas.py','assess'),('Scoring de destinos','meeting_areas.py','_area_score'),
        ('Congestión (actualización)','congestion.py','update'),
        ('Movimiento exterior','route_gateway.py','step'),('Movimiento interior','hazard_impact.py','step_with_hazards'),
        ('Fuego/humo','wind_simulation.py','step'),('Métricas','evacuation_metrics.py','sample')]
    for label,filename,method in categories:
        hits=[v[3] for k,v in stats.stats.items() if k[0].endswith(filename) and k[2]==method]
        rows.append((label,max(hits,default=0)))
    return rows
pb=prof(OUT/'profile_before.pstats');pa=prof(OUT/'profile_after.pstats')
profile_table=table(['Función/categoría','Antes, 5 turnos (s)','Después, 5 turnos (s)'],
                    [(b[0],fmt(b[1]),fmt(n[1])) for b,n in zip(pb,pa)])
oldhashes=json.loads((OUT/'before_hashes.json').read_text())
modified=[name.replace('\\','/') for name,digest in oldhashes.items() if hashlib.sha256((R/name).read_bytes()).hexdigest()!=digest]
new=[str(p.relative_to(R)).replace('\\','/') for folder in ['src','data','tests','tools'] for p in (R/folder).rglob('*')
     if p.is_file() and '__pycache__' not in str(p) and str(p.relative_to(R)) not in oldhashes]
purposes={
 'src/routing/meeting_flow.py':'guías multi-source, firma exacta y empalme a plaza individual',
 'src/routing/safe_routing.py':'cola, causas, watchdog, estabilidad y carga del router existente',
 'src/simulation/personal_safety.py':'ETA de dosis y margen personal sin tocar exposición física',
 'src/simulation/safety_score.py':'fórmula pedagógica fija con métricas originales conservadas',
 'tests/test_sixth_functional_changes.py':'52 pruebas específicas de sexta fase',
 'tools/compare_evacuation_modes_v2.py':'16 escenarios pareados, checkpoints y JSON/CSV',
 'tools/profile_evacuation.py':'medición aislada y ventana cProfile separada',
 'src/dcc_app/functional_application.py':'selección por cámara, diagnóstico y overlay opcional',
 'src/dcc_app/mode_application.py':'hook opcional de tecla D; legacy conserva su flujo',
 'src/integration/route_gateway.py':'callback opcional antes del paso, sin calcular rutas',
 'src/routing/intelligent_policy.py':'fuego completo, dosis, escape, prioridad y estabilidad',
 'src/routing/meeting_areas.py':'carga, guías, reservas y dispatch modular de política',
 'src/simulation/adaptive_exits.py':'salidas seguras y abandono de origen interior comprometido',
 'src/simulation/evacuation_metrics.py':'añade SafetyScore sin eliminar métricas',
 'src/simulation/functional_scenario.py':'conecta políticas, guías, trazas y máscara interior',
 'src/simulation/hazard_arrival.py':'arrays/consultas separados de fuego y humo',
 'src/simulation/hazard_impact.py':'hook de distancia interior, default legacy idéntico',
 'data/functional_scenario.json':'parámetros de sexta; valores existentes preservados'}
trace=json.loads((OUT/'fire_trace_S10.json').read_text())['fire_contact_traces']
trace_table=table(['Turno','Persona','Celda','Estado previo','ETA salida/evacuación previa'],[
    (e['turn'],e['person_id'],e['position'],e['diagnostic']['state'],e['diagnostic']['evacuation_eta']) for e in trace])
low=set(keys)-{'safe_meeting_arrivals','SafetyScore','temporary_goals'}
wins=[k for k in keys if (I[k]['mean']>T[k]['mean'] if k in ('safe_meeting_arrivals','SafetyScore') else
                         I[k]['mean']<T[k]['mean'] if k in low else False)]
losses=[k for k in keys if (I[k]['mean']<T[k]['mean'] if k in ('safe_meeting_arrivals','SafetyScore') else
                           I[k]['mean']>T[k]['mean'] if k in low else False)]
all_gates=all(v is True for v in bench['readiness_checks'].values())
status='READY' if all_gates and tests['failed_scripts']==0 else 'PARTIALLY READY'
sections=[]
def add(title,body):sections.append((title,body.strip()))
add('1. Resumen',f'''
Sexta fase implementada sobre `codex/sexta-fase-funcional`, preservando el trabajo
previo sin commit y sin push. Activos: ETA separadas, bloqueo temporal de fuego,
watchdog, dosis personal, causas de falta de ruta, escapes con historial,
estabilidad, guías compartidas, carga de reuniones y diagnóstico visual.

Estado medido: **{status}**. No se confunde tener tests aprobados con demostrar
superioridad universal. Las pérdidas se publican en secciones 21–24.
No se añadió física, ML ni dependencia.
''')
add('2. Diagnóstico de fire contacts',f'''
La quinta fase actualizaba primero fuego/humo, después ExposureTracker y por
último movimiento. Un alumno podía ser alcanzado en su celda antes de poder
moverse. El caso S10 fue repetido desde una copia intacta de quinta fase:
**los once contactos fueron interiores de E5**, todos por fuego que alcanzó
una celda ocupada durante la actualización. Ninguno fue un paso exterior de A*
hacia una celda ya incendiada. Nueve trazas llegaron a tener ETA de salida infinita.

{trace_table}

La ruta interior usa un potencial descendente; un origen que queda fuera del
campo dinámico podía perder incluso la posibilidad de salir hacia un vecino
seguro. Se añadió un hook que permite abandonar ese origen y un refugio local
estrictamente menos riesgoso dentro del mismo controlador. No se permite entrar
a fuego para salir de un encierro.

Persisten encierros en E16: solo tiene un grupo de salida, de tres pares finos,
en el JSON que esta fase debía conservar. No se inventaron puertas. Las trazas
finales, incluidas las regresiones, están en cada checkpoint del benchmark.
En los 16 Intelligent finales se registraron 47 contactos: 46 por avance del
fuego hacia una celda ocupada y uno ya ardiendo antes del primer turno
(S07, P232 en E15, foco inicial sobre su posición). Los 47 fueron interiores;
cero corresponden a personas exteriores. No se retiró ese foco del benchmark
para mejorar artificialmente el contador.
''')
add('3. Fire ETA y reglas de bloqueo','''
HazardArrivalField conserva `eta` (hazard_eta) y expone arrays `fire_eta` y
`smoke_eta`, además de consultas time_to_fire/time_to_smoke. Conserva el horizonte
60 y las tasas físicas originales. Se aplica clearance preventivo de una celda;
el margen inminente configurable es 3 turnos.

Para TODOS los puntos futuros de la ruta:
`fire_safety_margin = fire_eta - indice*movement_factor - maximum_delay_turns`.
Si es <=3 se rechaza. maximum_delay_turns sigue en 6; lentitud usa factor 2.
No hay grace de fuego. Humo/ETA combinada conserva muestreo cada tres puntos y
la excepción corta de escape del contrato anterior, separada de fuego.
Es una heurística conservadora de frente/proximidad, no el instante exacto
de ignición ni una cota probabilística garantizada ante brasas.
''')
add('4. Watchdog de ruta','''
ExternalRouteFollower.step admite `before_step` opcional; el default conserva
legacy. Justo antes de mover, la política comprueba fuego actual, fire ETA,
humo >=0.65 y plume previsto >=0.85. Rechazo: no hay paso, se invalida la
asignación, se elimina cooldown de reintento, se mantiene edad y se solicita
planificación urgente. También se aplica a objetivos intermedios.

La máscara preventiva alimenta al controlador interior existente. Un origen
comprometido no se interpreta como permiso para entrar a otro comprometido.
El watchdog no puede deshacer una ignición/avance ocurrido antes del movimiento.
''')
add('5. Time-to-toxic-dose','''
`simulation/personal_safety.py`:
`rate = max(current_smoke, 0.12*predicted_plume)`;
`toxic_dose_eta = max(0, 2.75-current_dose)/rate`.
Rate <0.0001 da infinito; incapacitación da cero. El plume es riesgo relativo,
no concentración futura medida; 0.12 es una aproximación didáctica configurable.
No se suma dosis predicha a ExposureTracker ni se modifican sus umbrales.
La dosis física sigue acumulándose por turno y se congela tras incapacitación.
''')
add('6. Personal safety margin','''
`personal_hazard_eta = min(environmental_hazard_eta, toxic_dose_eta)`;
`personal_safety_margin = personal_hazard_eta - evacuation_eta`.
Se publican ambas ETA, fire ETA, smoke ETA, margen y estado por alumno.
El viaje de una persona ralentizada se estima al doble de turnos, conservando
la acumulación por turno y movimiento real alternado originales.
Un residente crítico entra realmente en la cola de escape/reasignación, aunque
tenía una ruta de cero pasos. Una ruta que ya reduce la tasa de humo no se
descarta solo por repetir la alerta de dosis.
''')
add('7. Prioridad por dosis/riesgo','''
Pesos configurados: peligro de fuego inminente +1200; dosis ETA <=12 +600,
<=24 +280; se conservan margen crítico 300, urgencia 180, peligro actual 400,
laboratorio y exposición. Edad de espera sin límite usa 5 por turno, y edad
de cola añade 4. Dos plazas de equidad se reservan tras 24 turnos de espera,
después de la primera emergencia, para evitar starvation continuo.
La planificación ordinaria es 24 y el burst crítico/presión añade hasta 16,
con máximo compartido 40 búsquedas A* reales y solicitudes por turno.
''')
add('8. Causas de unassigned','''
Motivos por persona y agregados: ROUTE_BUDGET_EXHAUSTED, RETRY_COOLDOWN,
NO_SAFE_MEETING_AREA, NO_SAFE_ROUTE, CONGESTION_BLOCKED,
INTERMEDIATE_GOAL_PENDING, INCAPACITATED, NO_REACHABLE_PATH,
WAITING_FOR_CAPACITY. Los tests ejercitan las nueve causas.
`unassigned` conserva su definición: alumnos exteriores sin asignación,
incluidos incapacitados. Un objetivo intermedio asignado no se cuenta como
sin ruta ni como llegada a reunión. Interiores todavía buscando salida tienen
diagnóstico de estado/ETA, y no se mezclan con solicitudes exteriores.
''')
add('9. SafeIntermediateGoal mejorado','''
Orden: reunión segura, alternativa MARGINAL aceptable, escape con ganancia de
ETA, refugio local de menor riesgo y espera si no hay movimiento que mejore
seguridad. La búsqueda acotada usa el mismo CampusGraph; no es otro A*.
Score conserva ganancia ETA*2 y reducción de riesgo, y añade conectividad
local/dos saltos, preferencia upwind y penalización de plume/congestión.
Exige al menos tres pasos hasta objetivo y ganancia >=2 de ETA o >=3 de riesgo.
Rechaza callejones locales con menos de dos vecinos utilizables.
Registra risk_before_escape, risk_after_escape, hazard_eta_before/after,
objetivo y tipo ETA_ESCAPE/LOWER_RISK_REFUGE.
''')
add('10. Prevención de ping-pong','''
Historial de seis objetivos por persona; no se reutiliza un objetivo de los
últimos 32 turnos. Cooldown de escape 6, con excepción de fuego inminente.
No se afirma ausencia matemática de ciclos largos; la conectividad es local
y el cambio de viento/peligro puede justificar volver a una región.
''')
add('11. Replanning hard vs soft','''
Hard: peligro físico en ruta, reunión CLOSED, margen de fuego inaceptable,
watchdog y amenaza temporal fuerte. Dosis crítica de residentes y AVOID fuerte
pueden romper cooldown. Revisiones temporales incluyen rutas intermedias.
Soft: congestión/ocupación prolongada o mejora moderada. Usa intervalo 24,
hysteresis de margen 6 y evaluación de mejora antes de sustituir una ruta segura.
Una persona detenida lejos de la siguiente sección de ruta ya no causa por sí
sola una invalidación inmediata de todo el plan. Peligros físicos sí la causan.
''')
add('12. Route stability','''
Se registra route_stability_score a partir del margen temporal, acotado 0–1.
Antes de reemplazar una ruta segura se comparan máximo riesgo y coste acumulado
incluyendo distancia, riesgo y congestión. Requiere reducción de riesgo >=15%
o de coste >=20% sin aumentar riesgo. Si no mejora, se restaura el plan mediante
el gateway y se revierten reservas, cargas, destino, flujo y contadores.
Los avisos RUTA CONSERVADA tienen cooldown; conservar no omite el watchdog.
''')
add('13. Optimización de routing','''
El perfil indicó A* como cuello de botella. Se añadió una guía reverse
multi-source por reunión, usando SciPy ya instalado. Una matriz dispersa
representa el MISMO grafo cardinal transitable y los costes de riesgo/congestión.
El coste de arista invertida conserva el coste de entrar a la celda original.
El prefijo se comparte; una búsqueda local dentro de la reunión asigna una
plaza individual detrás del frente de entrada. Se eliminan loops del empalme.
A* ponderado queda como fallback, con presupuesto y validación idénticos.
Las guías pueden elegir un tronco/plaza distinto de los A* individuales de
quinta fase: no se afirma equivalencia de todos los planes históricos.
''')
add('14. Cache / flow fields / rutas compartidas',f'''
Firma exacta BLAKE2 de costes float64 y máscara de bloqueos; no se cuantiza
riesgo para reutilizar una guía. Máximo ocho campos por snapshot. Cambiar
coste o blocked cells invalida los campos. La caché puede desactivarse para
pruebas; cached/fresh/disabled producen el mismo plan con iguales entradas.
La ocupación y reservas individuales no se comparten y el gateway sigue
prohibiendo superposición. Cada plan reutilizado pasa validación temporal.

240 turnos medidos: A* {after['total_astar_searches']}; hits {after['cache_hits']};
misses {after['cache_misses']}; usos de guía {after['flow_field_usage']}.
Hits/misses cuentan consultas al campo compartido de un área; usage cuenta
trayectos candidatos producidos, que aún pueden ser rechazados temporalmente.
No son cantidades de personas evacuadas ni de planes finalmente aceptados.
''')
add('15. Balance de meeting areas','''
Cada área publica current_occupancy real de su región (también transeúntes sin
asignación), assigned_in_transit, predicted_arrival_rate, remaining_capacity y
congestion_near_area. Llegadas estimadas suman 1/pasos_restantes por viajero;
son una heurística de flujo, no aforo observado futuro. Se evita contar dos
veces a quienes ya están físicamente dentro al estimar plazas restantes.
La puntuación añade carga en tránsito/entrada, tasa prevista/entrada y congestión,
después de filtrar seguridad y ETA. Mantener un destino seguro conserva prioridad.
''')
add('16. Entry capacity','''
Precomputación geométrica: número de celdas del borde de reunión con al menos
un vecino transitable exterior a ella, mínimo uno. Es proxy de accesibilidad,
no personas/segundo calibradas. Pesos adicionales: entrada 12, tasa 10 y
congestión cercana 0.1. El llenado favorece plazas interiores para no formar
una pared de residentes en la primera línea de entrada.
''')
add('17. SafetyScore','''
Definido ANTES de las comparaciones, sin ajuste posterior para favorecer un modo:
`100 - 40*clip(incap/N) - 30*clip(fire_contacts/N)
     - 15*clip(dose/(N*2.75)) - 10*clip(unsafe_wait/(N*T))
     - 5*clip(destination_unsafe/N)`; clip en 0–1, resultado 0–100.
N=1879 y T=turnos ejecutados. Incapacitación/fuego concentran el 70% del peso;
dosis/espera/destinos resumen exposición y decisiones. Misma fórmula para ambos.
Todas las métricas crudas permanecen visibles. Puntuaciones altas pueden
coexistir con daños a una minoría y nunca certifican seguridad.
''')
add('18. Perfilado de rendimiento',f'''
cProfile en turnos 60–64, cinco turnos, antes/después. Duraciones acumuladas
por función; categorías pueden incluir subllamadas y no deben sumarse como
porcentajes exclusivos. El perfil NO es el tiempo aislado de 240 turnos.

{profile_table}

UI no se perfiló: se verificó mediante SDL dummy/render real. No se atribuye
un ahorro de FPS no medido.
''')
add('19. Rendimiento antes/después',f'''
Referencia histórica de quinta: 1.2467568 s/turno. Referencia reproducida al
iniciar esta tarea, snapshot sin cambios, 240 turnos: {before['elapsed_seconds']:.4f} s
total, {before['seconds_per_turn']:.6f} s/turno; incluye trazas diagnósticas externas.
Sexta, aislada sin UI ni assertions en el bucle: {after['elapsed_seconds']:.4f} s
total, {after['initialization_seconds']:.4f} s inicialización,
**{after['seconds_per_turn']:.6f} s/turno**.
Cambio contra referencia reproducida: {(after['seconds_per_turn']/before['seconds_per_turn']-1)*100:+.2f}%.
Objetivo <=0.8: {'cumplido' if after['seconds_per_turn']<=.8 else 'NO cumplido'}.
Hash físico final igual al snapshot: {before['physics_digest']==after['physics_digest']}.
Arrays residentes de guías medidos: {after['flow_array_bytes']} bytes;
no es RSS total ni memoria pico. Los tiempos concurrentes del benchmark
se reportan aparte y no se usan para afirmar el objetivo aislado.
Traditional actual, misma prueba aislada: 0.392133 s/turno. Intelligent sigue
siendo más caro que Traditional; recuperar rendimiento frente a quinta no
significa superar a Traditional en CPU.
La adición del codificador JSON estricto durante el timer desplazó líneas de
la herramienta y afectó el hash calculado por el inspector cargado. Se verificó
el código/datos de actores sin cambios y se recalculó solo ese fingerprint;
performance_after.json conserva inspector_fingerprint_at_timing y la nota.
No se editaron tiempos, trayectorias ni métricas medidas.

Resultado del mismo episodio de 240 turnos, quinta/sixth, sin seleccionar solo
indicadores favorables:

{table(['Métrica, 240 turnos','Quinta reproducida','Sexta'],[(k,fmt(before['metrics'][k]),fmt(after['metrics'][k])) for k in ['safe_meeting_arrivals','people_exposed_smoke','accumulated_smoke_dose','fire_contacts','incapacitated','unsafe_waiting_person_turns','unassigned','routes_recalculated','distance_traveled']])}
''')
add('20. Escenarios nuevos',f'''
Dieciséis escenarios, 160 turnos por modo: diez inputs históricos conservados
y seis dirigidos. Incluyen E15/E16, vegetación, foco cercano/downwind a reunión,
viento constante y brusco, dos reuniones amenazadas, alto humo persistente y
los tres pares finos del grupo principal de {primary_case['building']} incendiados. Se mantuvieron
semillas, viento y focos iguales dentro de cada par. Se comprobaron 161 hashes
físicos por caso, ocupación única y máximo una celda por turno.

Proveniencia: tras corregir residentes con dosis crítica y AVOID urgente se
volvieron a ejecutar los 16 Intelligent. Se conservaron 15 controles Traditional:
la única función de actor modificada fue IntelligentEvacuationPolicy.replan_reason,
que no se llama en Traditional (decision_policy=None). Se verificaron hashes de
todos los otros archivos/datos/ejecutor y igualdad AST excluyendo esa función;
hay prueba que hace fallar cualquier llamada a ella desde Traditional.
El par S15 se volvió a ejecutar con {primary_case['building']}, seleccionado por
máxima ocupación derivada de tamaño entre edificios con un grupo principal y
salidas secundarias explícitas. E31 tenía dos salidas con rol primary, y no se
presentó ese ensayo preliminar como prueba de uso de una secundaria formal.
No se afirma que se reejecutaron los otros quince controles.
Los checkpoints conservan execution_source_hash y execution_provenance;
reports/sexta_fase/traditional_control_reuse_proof.json contiene la prueba.
La estadística/CSV tiene hash de herramienta separado del fingerprint de actores.
Los reportes son JSON estricto; ETA diagnósticas no finitas se serializan como
las cadenas Infinity/-Infinity, sin convertirlas a una ETA inventada de cero.

Verificación adicional de S15: reproducción de 80 turnos con prefijo físico
idéntico al checkpoint; en E56, los 50 alumnos cruzaron salidas con rol secondary
(35 por este, 15 por norte). El grupo principal estuvo bloqueado. Evidencia:
reports/sexta_fase/blocked_primary_exit_diagnostic.json.

{scenario_rows}
''')
add('21. Resultados Traditional vs Intelligent',results)
add('22. Métricas donde Intelligent gana','Mejor media en este lote: '+', '.join(wins)+'.\n\nNo se extrapola a otros incendios. Temporal_goals es una acción, no una métrica donde más o menos implique automáticamente mejor seguridad.')
add('23. Métricas donde NO gana','Medias desfavorables: '+(', '.join(losses) if losses else 'ninguna de las métricas orientadas reportadas')+'.\n\n'+table(['Caso','Métrica','Traditional','Intelligent'],[(c['scenario_id'],k,fmt(c['traditional']['metrics'][k]),fmt(c['intelligent']['metrics'][k])) for c in cases for k in ['fire_contacts','incapacitated','accumulated_smoke_dose','unassigned'] if c['intelligent']['metrics'][k]>c['traditional']['metrics'][k]]))
add('24. Fire contacts antes/después',f'''
Mismos diez casos de quinta, Intelligent: {delta_text('fire_contacts')}
Lote ampliado de 16, medias T/I: {T['fire_contacts']['mean']:.4f} / {I['fire_contacts']['mean']:.4f}.
El foco predeterminado de 240 turnos pasó de {before['metrics']['fire_contacts']}
a {after['metrics']['fire_contacts']}. Estos ensayos no se mezclan como si fueran
el mismo protocolo. Las pérdidas de E16 se mantienen visibles y bloquean READY
si constituyen una regresión media.
''')
add('25. Unassigned antes/después',f'''
Mismos diez casos, Intelligent: {delta_text('unassigned')}
240 turnos predeterminados: {before['metrics']['unassigned']} → {after['metrics']['unassigned']}.
Distribuciones por causa final se conservan en cada checkpoint y resumen.
No se elimina a los incapacitados del contador para mejorar artificialmente el resultado.
''')
add('26. Replans antes/después',f'''
Mismos diez casos, Intelligent: {delta_text('routes_recalculated')}
240 turnos predeterminados: {before['metrics']['routes_recalculated']} → {after['metrics']['routes_recalculated']}
({(after['metrics']['routes_recalculated']/before['metrics']['routes_recalculated']-1)*100:+.2f}%).
Se distinguen propuestas rechazadas, planes realmente aceptados, invalidaciones,
watchdog y guías. No se cuenta una propuesta revertida como un replan aceptado.
''')
add('27. UI / diagnósticos','''
Sin cambiar ventana ni estilo global: clic después de A selecciona al alumno
más cercano mediante la misma cámara/zoom/viewport; clic antes de A conserva
selección de foco. Panel compacto muestra estado, destino, margen, ETA fuego,
humo, dosis, motivo y prioridad de la última decisión. TAB sigue disponible
para sensores. D alterna overlay de DynamicRiskField, incluido plume previsto,
apagado por defecto. Avisos con cooldown y deque de seis; solo pocos visibles.
Se conservaron zoom, pan, rueda, pausa y mensaje exacto de tortugas.
''')
add('28. Archivos creados','\n'.join('- `'+p+'`: '+purposes.get(p,'soporte de sexta fase')+'.' for p in new)+'\n- `SIXTH_FUNCTIONAL_CHANGES_FEEDBACK.md`: este handoff.\n\nLos scripts de auditoría, snapshots y ensayos de hipótesis están en reports/sexta_fase, ignorados por Git; no son dependencias del producto.')
add('29. Archivos modificados','\n'.join('- `'+p+'`: '+purposes.get(p,'integración de sexta fase')+'.' for p in modified)+'\n- `README.md`: comandos, configuración, métricas y límites de sexta fase.\n\nNo se movieron/eliminaron archivos de aplicación. Cambios ajenos de Chagoya quedaron intactos. No hubo commit, push ni conflictos; el trabajo permanece revisable en la rama codex/sexta-fase-funcional.')
add('30. Tests',f'''
Suite completa en copia temporal headless, incluyendo PostgreSQL real opcional
disponible en esta máquina: **{tests['passed_scripts']}/{tests['scripts']} scripts,
{tests['unit_tests']} unittest, {tests['failed_scripts']} scripts fallidos,
{tests['skipped']} omitidos**. Los scripts históricos también ejecutan asserts
que no aparecen como unittest. Log: reports/sexta_fase/tests_final/results.json.
Tras corregir el fixture S15 para exigir un rol secondary real, se repitieron
las 52 pruebas específicas; el código de la aplicación permaneció igual.

Nuevas pruebas: fuego en todos los puntos, margen, watchdog, no alternativa,
dosis, residente crítico, rutas ya escapando, nueve motivos, equidad, escapes,
historial/upwind, rollback, estabilidad, caché invalidada, fallback A*, aforo,
datos de escenarios, UI real y física idéntica. Los fallos iniciales de fixtures
NO_SAFE_ROUTE se corrigieron diferenciando destino no disponible y barrera
temporal. No se ocultaron fallos finales.
''')
add('31. Problemas encontrados','''
- Contactos interiores antes del movimiento, imposibles de arreglar solo con A*.
- El primer prototipo de clearance=2 encerraba personas adyacentes al foco;
  se conservó clearance=1 y se permitió abandonar un origen comprometido.
- E16 conserva una sola salida; fuego/humo/cuerpos pueden cortar su acceso.
- Dos hipótesis locales no promovidas: conservar más la cola dio 19 contactos/
  84 incapacitados; además ordenar frente primero dio 17/79 frente a 18/76
  de la versión evaluada en ese ensayo. No se eligieron por una métrica aislada.
- Se corrigió ocupación real frente a residentes asentados, rollback de flujo,
  y prioridad de dosis que no llegaba a la cola de un residente.
- Se corrigió el resumen estadístico: peor SafetyScore es el mínimo, no máximo.
  Fórmula/pesos del score no cambiaron después de fijarlos.
- Los reportes preliminares están separados; no se mezclan sus cifras con el final.
''')
add('32. Limitaciones','''
Modelo didáctico sintético, no plan de seguridad real ni predictor médico,
de incendios o de meteorología. ETA usa distancias/tasas aproximadas y no
conoce sorteos futuros de brasas. El plume no es concentración futura medida.
Bloqueo conservador puede rechazar un camino que físicamente hubiera sido viable;
no se permite entrar a fuego para mejorar el contador de llegadas.
Encierro interior, estrechamiento, cuerpos y futuros focos pueden impedir salida.
Conectividad local del escape no garantiza salida global de un cul-de-sac.
Exposición y fire_contact de ExposureTracker son absorbentes: tras incapacitación
no acumula más dosis ni nuevos contactos. Fire_contacts conserva esa definición
histórica; no es un censo de cuerpos alcanzados después. Se publican también
incapacitados, dosis y trazas para no interpretar el contador aisladamente.
Unassigned puede incluir incapacitados. Tiempos de llegada están censurados
a quienes llegaron. El contador de sin asignación se toma en la fase exterior;
quienes cruzan una puerta al final del turno entran en su cola al siguiente,
preservando la secuencia y la definición histórica del contador.
SafetyScore puede diluir daños de una minoría.
`safe_meeting_arrivals` conserva el conteo espacial de una plaza asignada en
una reunión disponible; no certifica salud, y puede incluir a alguien que se
incapacitó después de llegar. Incapacitados se publica por separado.
La espera insegura comparativa conserva el observador ambiental común de quinta;
el diagnóstico/cola personal sí utiliza dosis. No se cambiaron retroactivamente
esas definiciones para favorecer a Intelligent.
No se afirma que las guías repliquen todos los A* históricos ni que Intelligent
gane en cada caso. El predictor sigue aprendiendo patrones sintéticos.
''')
add('33. Cosas que NO cambiaste','''
Grid 480×300; población 1879 y fórmula; datos derivados del campus, vegetación,
puertas y ocho reuniones; física/velocidad/combustible del fuego; humo,
spotting y RNG; viento real; Ridge/persistencia; sensores/contrato y
fire_within_2_cells; Persona 2; PostgreSQL; base A*; pesos de congestión;
desplazamiento máximo de una celda; legacy; resolución/estilo general/sliders;
mensaje de tortugas. No hay nuevas dependencias. Integridad comprobada por hashes
contra snapshot al comenzar y por tests existentes.
''')
add('34. Comandos para ejecutar','''
Desde DisasterCommandCenter/ con venv activo:
```powershell
pip install -r requirements.txt
python main.py
python main.py --evacuation-mode traditional
python main.py --legacy
python main.py --smoke-test
python tests/test_sixth_functional_changes.py
python tools/run_tests.py
python tools/profile_evacuation.py --turns 240 --profile
python tools/compare_evacuation_modes_v2.py --turns 160 --workers 3
```
Para incluir DB sin omisiones, instalar requirements-persona2-db.txt y configurar
DCC_POSTGRES_BIN (binarios PostgreSQL) o DCC_TEST_DATABASE_URL de pruebas;
`python tools/run_tests.py --require-db`. Nunca apuntar una prueba a datos reales.
Informes de benchmark: reports/evacuation_comparison_v2/summary.json,
summary.csv y per_scenario.csv. Verificar fingerprint con --resume; ejecutarlo
sin --resume fuerza medición nueva. Los reports no están versionados.
''')
add('35. Estado final',f'''
**{status}**

Comprobaciones finales (True=superada):
```json
{json.dumps(bench['readiness_checks'],indent=2)}
```
{'Se cumplen los criterios medidos del lote y rendimiento aislado, dentro de las limitaciones descritas.' if status=='READY' else 'La implementación y los tests están terminados, pero los criterios de éxito medidos no se cumplen todos. No se presenta como una evacuación resuelta ni se ocultan regresiones. El siguiente trabajo debe centrarse en las pérdidas interiores documentadas, sin relajar bloqueos ni alterar física para mejorar las cifras.'}
''')
assert len(sections)==35
text='# Disaster Command Center — Sixth Functional Changes Feedback\n\n'+'\n\n'.join('## '+title+'\n\n'+body for title,body in sections)+'\n'
(R/'SIXTH_FUNCTIONAL_CHANGES_FEEDBACK.md').write_text(text,encoding='utf-8')
print(status,len(text),'chars',len(sections),'sections')
