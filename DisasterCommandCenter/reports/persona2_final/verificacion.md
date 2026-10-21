# Verificación final de Persona 2

| Comprobación | Resultado |
| --- | --- |
| Scripts DisasterCommandCenter | 25 aprobados |
| Pruebas unitarias Persona 2 | 130 aprobadas |
| Pruebas previas de Chagoya | 20 aprobadas |
| Pruebas omitidas | Ninguna |
| Archivos previos conservados | True |
| PostgreSQL | 18.4 real, con clústeres temporales |
| Pygame | Arranque SDL dummy comprobado |

La ejecución de PostgreSQL de prueba se detuvo y sus datos temporales se eliminaron.
La aplicación permanente utiliza la variable DCC_DATABASE_URL.
No se modificaron los motores ni se sobrescribió el trabajo previo de Chagoya.

## Arranques gráficos verificados

- [OK] Pygame sin pantalla: 3 fotogramas en modo original.
- [OK] Pygame sin pantalla: 3 fotogramas en modo original.

## Pruebas por script

| Script | Exit code | Unit tests |
| --- | ---: | ---: |
| test_app_modos_14_4_4.py | 0 | — |
| test_centro_evacuacion.py | 0 | — |
| test_distribucion_personas.py | 0 | — |
| test_efectos_personas.py | 0 | — |
| test_ejemplo_persona3_15_2_3.py | 0 | — |
| test_entrega_persona2_15_1.py | 0 | — |
| test_integracion_aislada_14_3_5.py | 0 | — |
| test_integral_14_4_5.py | 0 | — |
| test_interfaz_rutas.py | 0 | — |
| test_persona2_baseline.py | 0 | 19 |
| test_persona2_dataset.py | 0 | 13 |
| test_persona2_eda.py | 0 | 16 |
| test_persona2_end_to_end.py | 0 | 6 |
| test_persona2_gateway.py | 0 | 10 |
| test_persona2_inference.py | 0 | 16 |
| test_persona2_ingestion.py | 0 | 19 |
| test_persona2_model_comparison.py | 0 | 16 |
| test_persona2_postgres.py | 0 | 15 |
| test_personas_interiores.py | 0 | — |
| test_salida_edificios.py | 0 | — |
| test_selector_modo_14_3_6B.py | 0 | — |
| test_sensores.py | 0 | — |
| test_simulacion_fuego.py | 0 | — |
| test_simulacion_humo.py | 0 | — |
| test_simulacion_viento.py | 0 | — |

## Chagoya

~~~text
....................                                                     [100%]
20 passed in 0.12s
~~~
