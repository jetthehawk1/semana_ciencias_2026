from pathlib import Path
import hashlib,json,math,re
from statistics import mean,median
ROOT=Path(__file__).resolve().parents[2]
report=json.loads((ROOT/'reports/evacuation_comparison/summary.json').read_text(encoding='utf-8'))
tests=json.loads((ROOT/'reports/quinta_fase/tests_final/results.json').read_text())
perf=json.loads((ROOT/'reports/quinta_fase/performance.json').read_text())
assert report['complete'] and len(report['scenarios'])==10
assert all(c['identical_physical_trajectory'] for c in report['scenarios'])
assert tests['summary']['failed_scripts']==0
assert perf['identical_fire'] and perf['identical_smoke']
source_inputs=sorted((ROOT/'src').rglob('*.py'))+[ROOT/'data/functional_scenario.json',ROOT/'tools/compare_evacuation_modes.py']
assert hashlib.sha256(b''.join(p.read_bytes() for p in source_inputs)).hexdigest()==report.get('evaluation_source_hash',report['source_hash'])
assert perf['identical_decision_summary_after_cost_cache']
assert json.loads((ROOT/'reports/quinta_fase/cost_cache_equivalence.json').read_text())['identical_paths']==65
assert report['metric_postprocessing']['verified_physical_replays']==10
old=json.loads((ROOT/'reports/quinta_fase/before/protected_hashes.json').read_text())
assert all(hashlib.sha256((ROOT/n).read_bytes()).hexdigest()==h for n,h in old.items())
before_config=json.loads((ROOT/'reports/quinta_fase/before/data/functional_scenario.json').read_text())
now=json.loads((ROOT/'data/functional_scenario.json').read_text())
assert all(now[k]==v for k,v in before_config.items())
def f(x):
 if x is None:return 'no alcanzado'
 if isinstance(x,int):return str(x)
 return f'{x:.4f}'
def table(headers,rows):
 return '| '+' | '.join(headers)+' |\n|'+'|'.join(' --- ' for _ in headers)+'|\n'+'\n'.join('| '+' | '.join(map(str,row))+' |' for row in rows)
cases=report['scenarios'];agg=report['aggregate']
setup='Se ejecutaron **10 escenarios × 2 modos × 160 turnos = 3,200 turnos**, sin ventana.\n\n'
setup+='Mapa, 1,879 posiciones iniciales, entradas, semilla de incendio e inputs de viento idénticos dentro de cada par. El fuego/humo no dependen de la decisión de personas. Se verificó su hash exacto en cada turno (161 estados por modo y escenario). Ninguna predicción conoce el programa de controles futuros.\n\n'
setup+='Primer foco E30 por defecto; otros nueve edificios se seleccionaron con Random(2026) sin elegir resultados favorables. La celda de cada edificio se deriva de geometría efectiva, próxima al centro. Los primeros cinco casos tienen viento constante; los últimos cinco cambian dirección cada 40 turnos y velocidad sinusoidal controlada.\n\n'
setup+=table(['Caso','Edificio','Seed','Foco fino','Viento inicial','Patrón'],[(c['scenario_id'],c['building'],c['seed'],str(c['ignition']),f"{c['wind_inputs'][0][0]} {c['wind_inputs'][0][1]:.4f}",'constante' if i<5 else 'rotación/rampa') for i,c in enumerate(cases)])
setup+='\n\nDespués del lote se corrigió exclusivamente el contador diagnóstico para excluir salidas desde celdas ya peligrosas: se repitió la física de los diez escenarios (sin volver a mover personas), verificando los 161 hashes por escenario, y se reconstruyó el estado ambiental en cada salida registrada. Las métricas de movimiento/exposición permanecieron intactas. El archivo conserva source_hash de la ejecución y evaluation_source_hash del evaluador final. Los checkpoints guardan la versión del postprocesado.\n\nLa última optimización solo memoiza costes inmutables dentro de cada A*: no cambia valores, algoritmo, heurística o desempates. Se verificaron 65 rutas exactas antes/después (40 grafos y 25 solicitudes reales) y un episodio de 240 turnos con resumen de decisiones idéntico. No se presenta como una nueva ejecución de las veinte evacuaciones. Hash del evaluador final: `'+report['evaluation_source_hash']+'`.'
setup+='\n\nComando: `python tools/compare_evacuation_modes.py --scenarios 10 --turns 160`. Resultados completos JSON y CSV en `reports/evacuation_comparison/`, incluidos checkpoints por escenario/modo y manifiestos de inputs. Source hash de ejecución: `'+report['source_hash']+'`.\n\nAmbos modos usan base 24 y burst 40 por presión de cola; la diferencia de seguridad no procede de otorgar más presupuesto nominal al modo inteligente.'
keys=['safe_meeting_arrivals','mean_turns_to_first_meeting','people_exposed_smoke','accumulated_smoke_dose','people_close_to_fire','fire_contacts','incapacitated','routes_recalculated','preventive_reassignments','maximum_congestion','distance_traveled','people_in_cells_that_later_became_hazardous','unsafe_waiting_person_turns','destination_became_unsafe_before_arrival','confirmed_forecast_departures','temporary_goals','unassigned']
per=[]
for c in cases:
 per.append('**'+c['scenario_id']+' — '+c['building']+'**\n\n'+table(['Métrica','Traditional','Intelligent'],[(k,f(c['traditional']['metrics'][k]),f(c['intelligent']['metrics'][k])) for k in keys]))
per='\n\n'.join(per)+'\n\nLos tiempos son primera llegada entre quienes llegaron; no son tiempo de evacuación de toda la población. La ocupación de una reunión disponible y la incapacidad se informan por separado; ocupar una plaza no certifica seguridad personal. `safe_meeting_arrivals` es ocupación final de plazas disponibles, no toda salida del edificio. La dosis mantiene la semántica absorbente de ExposureTracker.'
rows=[]
for k,v in agg['traditional'].items():
 if v is None:continue
 w=agg['intelligent'][k]
 rows.append([k,' / '.join(f(v[x]) for x in ['mean','median','worst']),' / '.join(f(w[x]) for x in ['mean','median','worst'])])
aggregated=table(['Métrica','Traditional: media / mediana / peor','Intelligent: media / mediana / peor'],rows)
aggregated+='\n\nPara llegadas seguras y personas que alcanzaron reunión, peor=min; para tiempos/exposición/costes, peor=max. Para contadores diagnósticos (escapes, replanes, confirmaciones), peor representa máximo observado, no valoración de seguridad. Los tiempos sin llegadas serían null, nunca cero.'
wins=[];losses=[]
for c in cases:
 t=c['traditional']['metrics'];i=c['intelligent']['metrics']
 better=[k for k in ['incapacitated','accumulated_smoke_dose','unsafe_waiting_person_turns'] if i[k]<t[k]]
 if better:wins.append('- '+c['scenario_id']+': '+', '.join(k+f' {f(t[k])} → {f(i[k])}' for k in better)+'.')
 bad=[k for k in ['incapacitated','accumulated_smoke_dose','unsafe_waiting_person_turns','fire_contacts','people_close_to_fire','people_exposed_smoke','destination_became_unsafe_before_arrival'] if i[k]>t[k]]
 if bad:losses.append('- '+c['scenario_id']+': '+', '.join(k+f' {f(t[k])} → {f(i[k])}' for k in bad)+'.')
win_text='\n'.join(wins)+'\n\n'+table(['Métrica de riesgo','Gana Intelligent','Empata','Gana Traditional'],[(k,v['intelligent_wins'],v['ties'],v['traditional_wins']) for k,v in agg['paired_risk_comparison'].items()])
loss_text=('\n'.join(losses) if losses else 'No hubo pérdidas en los indicadores de riesgo enumerados dentro de estos diez casos; esto no demuestra ausencia de pérdidas en otros escenarios.')
returns=[]
for c in cases:
 previous={}
 for e in c['intelligent']['destination_changes']:
  if e['from']=='INTERMEDIATE' or e['to']=='INTERMEDIATE':continue
  old_event=previous.get(e['person_id'])
  if old_event and old_event['from']==e['to'] and old_event['to']==e['from'] and e['turn']-old_event['turn']<=12:
   returns.append((c['scenario_id'],e['person_id'],old_event['turn'],e['turn'],e['reason']))
  previous[e['person_id']]=e
loss_text+=f'\n\nSe observaron {len(returns)} retornos A→B→A en <=12 turnos: '+str(returns)+'. Son excepciones de emergencia al cooldown; no se afirma que cada retorno haya sido óptimo. La prueba de destino estable sin amenaza sigue pasando.'
loss_text+='\n\nNo se afirma superioridad en distancia recorrida, número de recálculos ni todos los tiempos de llegada. Un rodeo seguro puede ser más largo y costoso. Se publican esos valores arriba. Las métricas de viento no se reentrenaron: en la cuarta fase persistencia ganó a Ridge en error angular/velocidad; se conserva ese límite. Los resultados de fuego no permiten atribuir una pérdida particular a una causa exacta sin una traza individual adicional.'
b=perf['before'];a=perf['after'];delta=(a['seconds_per_turn']/b['seconds_per_turn']-1)*100
performance=table(['Medición secuencial, 240 turnos','Inicio (s)','Total (s)','Media por turno (s)'],[(name,f(v['initialization_seconds']),f(v['elapsed_seconds']),f(v['seconds_per_turn'])) for name,v in [('Cuarta fase restaurada',b),('Quinta fase final sin cache',perf['uncached_final']),('Quinta fase final con cache',a)]])
performance+='\n\nLa primera quinta fase midió '+f(perf['unoptimized']['seconds_per_turn'])+' s/turno. La comprobación de componentes sola midió '+f(perf['connectivity_only']['seconds_per_turn'])+' s/turno y preservó exactamente el resumen completo. El límite global de búsquedas reales se agregó después, porque el límite anterior permitía hasta tres A* por solicitud. Por sí solo midió '+f(perf['budget_cap_only']['seconds_per_turn'])+' s/turno. Después se añadió escape local prioritario y reconocimiento de residentes inmóviles; la fila final corresponde a esa versión completa. Sus cambios de planificación requieren y recibieron un lote nuevo completo.\n\n'
performance+=f"\n\nVariación del bucle: {delta:+.2f}%. Ambas mediciones usan E 0.75, seed 2026, foco (235,166), administrador optimizado, 240 llamadas sin render ni assertions en el bucle medido. Se restauraron los archivos de la cuarta fase en una copia temporal; no se modificó la aplicación para medir. Fuego y humo finales fueron idénticos por hash.\n\n"
performance+='Referencia histórica de cuarta fase: 0.401758 s/turno con verificaciones; no es exactamente el mismo protocolo de esta medición. El lote pareado incluye hashes/verificaciones; los primeros casos coincidieron con otras pruebas y los últimos se completaron con tres procesos independientes en 12 CPUs lógicas. Sus tiempos no se usan como una medida aislada de rendimiento. La medición antes/después siguiente se ejecutó secuencialmente tras acabar ese lote.\n\n'
performance+=table(['Modo, lote completo','Total (s)','Media de s/turno','Mediana de s/turno'],[(m,f(sum(c[m]['elapsed_seconds'] for c in cases)),f(mean(c[m]['seconds_per_turn'] for c in cases)),f(median(c[m]['seconds_per_turn'] for c in cases))) for m in ['traditional','intelligent']])
performance+='\n\nOptimizaciones intentadas: límite de búsquedas A* reales, obstáculos persistentes comunes a ambos modos, espera consecutiva antes de replanificar, campo compartido vectorizado y un único array de coste combinado, distancias de salida/geométricas en caché, observación de posiciones históricas mediante NumPy y recálculo por ocupación menos frecuente. Se conservan los pesos de congestión. Los arrays directos de ETA/coste/coordenadas ocupan '+'0'+' bytes (ver nota de memoria abajo).'
# Do not pretend to measure RSS: calculate allocation sizes explicitly from known array shapes/dtypes.
performance=performance.rsplit(' Los arrays directos',1)[0]
performance+='\n\nLa caché redujo el bucle de '+f(perf['uncached_final']['seconds_per_turn'])+' a '+f(a['seconds_per_turn'])+' s/turno, pero **no se alcanzó el objetivo de rendimiento** frente a la cuarta fase. Sigue siendo una limitación importante; no se oculta bajo la velocidad nominal x1.75. El perfil de cinco turnos tardíos encontró el coste principal en búsquedas A* ponderadas.\n\n'
summary=a['summary']
performance+=table(['Episodio final 240 turnos, E 0.75','Valor real'],[(k,summary[k]) for k in ['dentro','salieron','movimientos']]+[('en reunion',summary['meeting']['gathered']),('sin asignacion',summary['meeting']['unassigned']),('incapacitados',summary['riesgo']['incapacitada']),('celdas de fuego',summary['fuego']['burning']),('celdas de humo',summary['humo']['smoky_cells']),('rutas recalculadas',summary['meeting']['replanned_routes']),('maximo A* por turno',summary['meeting']['maximum_astar_searches'])])
performance+=' Los cuatro arrays estáticos directos de HazardArrivalField (eta/coste float32, x/y int64) suman 3,456,000 bytes; se crean temporales de trabajo por turno. No es una medida de RSS ni de memoria pico.'
s=tests['summary']
test_text=f"Suite completa final: **{s['passed_scripts']}/{s['scripts']} scripts, {s['unit_tests']} unittest, {s['failed_scripts']} fallos, {s['skipped']} omisiones**. PostgreSQL opcional se probó con el runtime local disponible; no se necesitó para la app.\n\n"
test_text+='```powershell\npython tests/test_fifth_functional_changes.py\npython tools/run_tests.py --require-db --output-dir reports/quinta_fase/tests_final\npython main.py --smoke-test\npython main.py --evacuation-mode traditional --smoke-test\npython main.py --legacy --smoke-test\n```\n\nSe ejecutaron primero las suites relacionadas y después el conjunto completo en copia temporal aislada con SDL dummy. Se configuró DCC_POSTGRES_BIN para --require-db; no se imprimieron credenciales. Logs/resultados: `reports/quinta_fase/tests_final/results.json`.\n\n'
test_text+='Las 31 pruebas nuevas cubren los trece casos fundamentales, cambio circular de viento heredado mediante las suites previas, ETA inmediata/sin focos, velocidad reducida, presupuesto simétrico, avisos con cooldown, mismo fuego/humo por turno, ocupación única, paso máximo uno, confirmación observada separada de mero replan y de abandono reactivo, caché de costes por búsqueda, activación/desactivación ETA y agregación sin afirmar mejoras inexistentes. La prueba grupal verifica posiciones reales antes del umbral, no solo flags.\n\n'
test_text+=f'Integridad: {len(old)} archivos protegidos conservan SHA-256 (motores, assets, contratos, Persona 2, telemetría y predictor). Todos los valores de configuración previos se conservaron; solo se añadieron bloques. El lote verifica igualdad física de 1,610 estados pareados.'
problems='Se detectaron pérdidas en indicadores concretos; se documentan en sección 21. '
problems+='La ETA y los rodeos no garantizan seguridad universal. '
problems+='Traza de la primera versión, antes del límite global real de A*, E15: después del turno 120 hubo 60 nuevas incapacidades en Intelligent frente a 27 en Traditional. De las 60, 53 estaban WAITING_UNSAFE en el turno previo; 37 no tenían asignación, 15 conservaban un objetivo intermedio y 8 iban a R2. Las 60 fueron por dosis de humo, no por contacto directo. El origen E8 aportó 29 incapacitados; solo cuatro incapacitados de todo el episodio Intelligent seguían dentro. Esto muestra que identificar riesgo no garantiza evacuar una cola o salir de un corredor ocupado antes de acumular dosis. El viento real cambió de E a SE en el turno 121; no se atribuye causalidad exclusiva al viento sin un contrafactual adicional. Trazas anteriores preservadas: reports/quinta_fase/regression_unoptimized_traditional.json y regression_unoptimized_intelligent.json. No se presentan como métricas de la versión final; la comparación final se repitió después de corregir presupuesto. '

problems+='En el lote quedaron personas sin destino/ruta: '+', '.join(c['scenario_id']+f" T={c['traditional']['metrics']['unassigned']}, I={c['intelligent']['metrics']['unassigned']}" for c in cases)+'.'
ready=agg['consistent_risk_improvement'] and delta<50 and agg['paired_risk_comparison']['fire_contacts']['mean_delta']<=0
status=('**READY**' if ready else '**PARTIALLY READY**')+'\n\n'
status+=('La aplicación y comparación están terminadas, con las suites aprobadas e igualdad física verificada. Intelligent reduce de forma consistente dosis, incapacitados y espera insegura según el criterio pareado publicado, conservando pérdidas explícitas en otros indicadores. READY se limita a esta base didáctica y a los escenarios medidos.' if ready else 'La implementación está activa y las pruebas pasan. El criterio primario del JSON considera incapacitados, dosis y espera insegura; no autoriza por sí solo READY si suben los contactos directos o el coste por turno supera el criterio conservador. Las regresiones y tiempos medidos se detallan arriba. Se mantiene PARTIALLY READY hasta resolver y volver a medir los indicadores que fallan. No se afirma superioridad general.')
configuration='```json\n'+json.dumps({k:now[k] for k in ['hazard_arrival','intelligent_evacuation','route_safety','meeting_assignment','route_scheduling','comparison']},ensure_ascii=False,indent=2)+'\n```'
status+='\n\nMedias finales Traditional → Intelligent: incapacitados '+f(agg['traditional']['incapacitated']['mean'])+' → '+f(agg['intelligent']['incapacitated']['mean'])+', dosis '+f(agg['traditional']['accumulated_smoke_dose']['mean'])+' → '+f(agg['intelligent']['accumulated_smoke_dose']['mean'])+', contactos directos '+f(agg['traditional']['fire_contacts']['mean'])+' → '+f(agg['intelligent']['fire_contacts']['mean'])+'. Pendientes: coste de planificación, contactos con fuego, ETA personal por dosis y vigilancia temporal completa de rutas intermedias.'
values=dict(CONFIGURATION=configuration,COMPARISON_SETUP=setup,PER_SCENARIO=per,AGGREGATE=aggregated,WINS=win_text,LOSSES=loss_text,PERFORMANCE=performance,TESTS=test_text,EXTRA_PROBLEMS=problems,FINAL_STATUS=status)
p=ROOT/'FIFTH_FUNCTIONAL_CHANGES_FEEDBACK.md';text=p.read_text(encoding='utf-8')
for key,value in values.items():text=text.replace('{{'+key+'}}',value)
text=text.replace('Este documento se completa con mediciones reales antes de cerrar la entrega.','Validación terminada: resultados medidos y limitaciones detallados a continuación.')
assert '{{' not in text
assert len(re.findall(r'^## \d+\.',text,re.M))==31
p.write_text(text,encoding='utf-8')
print('Feedback finalized:',status,flush=True)
