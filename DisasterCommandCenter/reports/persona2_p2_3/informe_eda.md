# Persona 2 — P2.3: analisis exploratorio

Fuente: synthetic_simulation; ejecucion: dcc_14_4_3_sesion_0001.

| Medida | Valor |
| --- | ---: |
| records | 432 |
| sensor_count | 12 |
| turn_count | 36 |
| first_turn | 0 |
| last_turn | 35 |
| feature_count | 3 |
| missing_required_values | 0 |
| allowed_null_values | 72 |

## Columnas de P2.2

| Columna | Rol | Tipos observados (conteos) | Nulos permitidos | Ausentes obligatorios |
| --- | --- | --- | ---: | ---: |
| temperature_c | feature | float: 432 | 0 | 0 |
| smoke_index | feature | float: 432 | 0 | 0 |
| alarm | feature | int: 432 | 0 | 0 |
| schema_version | metadata | str: 432 | 0 | 0 |
| run_id | metadata | str: 432 | 0 | 0 |
| turn | metadata | int: 432 | 0 | 0 |
| sensor_id | metadata | str: 432 | 0 | 0 |
| x | metadata | int: 432 | 0 | 0 |
| y | metadata | int: 432 | 0 | 0 |
| building_id | metadata | NoneType: 72, str: 360 | 72 | 0 |
| fire_within_2_cells | target | bool: 432 | 0 | 0 |

## Target: fire_within_2_cells

| Clase | Lecturas | Porcentaje |
| --- | ---: | ---: |
| false | 386 | 89.35% |
| true | 46 | 10.65% |

Clase unica: False. Desbalance segun umbral del 80%: True.

## Temperatura y humo

Desviacion estandar poblacional (ddof=0); sin redondeo adicional en JSON.

| Variable | n | Min | Max | Media | Mediana | Desv. poblacional |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| temperature_c | 432 | 23.852000 | 109.137000 | 29.589296 | 24.014000 | 17.971957 |
| smoke_index | 432 | 0.000000 | 1.000000 | 0.165050 | 0.002045 | 0.275682 |

Alarma: 126 activas (29.17%) y 306 inactivas.

## Cobertura por sensor

| Sensor | Lecturas | Target false | Target true |
| --- | ---: | ---: | ---: |
| S-E1-01 | 36 | 36 | 0 |
| S-E1-02 | 36 | 36 | 0 |
| S-E10-01 | 36 | 36 | 0 |
| S-E10-02 | 36 | 36 | 0 |
| S-E15-01 | 36 | 36 | 0 |
| S-E15-02 | 36 | 36 | 0 |
| S-E25-01 | 36 | 36 | 0 |
| S-E25-02 | 36 | 36 | 0 |
| S-E30-01 | 36 | 13 | 23 |
| S-E30-02 | 36 | 24 | 12 |
| S-EXT-01 | 36 | 25 | 11 |
| S-EXT-02 | 36 | 36 | 0 |

## Cobertura por turno

| Turno | Lecturas |
| --- | ---: |
| 0 | 12 |
| 1 | 12 |
| 2 | 12 |
| 3 | 12 |
| 4 | 12 |
| 5 | 12 |
| 6 | 12 |
| 7 | 12 |
| 8 | 12 |
| 9 | 12 |
| 10 | 12 |
| 11 | 12 |
| 12 | 12 |
| 13 | 12 |
| 14 | 12 |
| 15 | 12 |
| 16 | 12 |
| 17 | 12 |
| 18 | 12 |
| 19 | 12 |
| 20 | 12 |
| 21 | 12 |
| 22 | 12 |
| 23 | 12 |
| 24 | 12 |
| 25 | 12 |
| 26 | 12 |
| 27 | 12 |
| 28 | 12 |
| 29 | 12 |
| 30 | 12 |
| 31 | 12 |
| 32 | 12 |
| 33 | 12 |
| 34 | 12 |
| 35 | 12 |

## Alcance e interpretacion

- Datos sinteticos: no representan sensores fisicos reales.
- Los turnos son pasos de simulacion, no segundos ni fechas.
- El analisis solo recibe paquetes que superan P2.1; un paquete invalido se rechaza.
- building_id=None es valido para sensores exteriores; no es una medicion perdida.
- Los tipos corresponden a P2.2: mediciones float, alarm int 0/1, target bool.
- fire_within_2_cells se analiza como target y permanece fuera de X.
- Desbalance: regla descriptiva de clase mayoritaria >=80%, no criterio universal.
- Las lecturas de un mismo sensor y turnos cercanos no son muestras independientes.

## SHA-256 del paquete analizado

- lecturas_sensores.csv: c8c6c1efae51824bedf876ddd94e67519db59224867d84fb4b5bf71761ea652b
- lecturas_sensores.jsonl: dd3ba0b935f796a1e72cc0ab4715884c1ae42a2c50b7d0e29890e5e9b784a480
- manifiesto_sensores.json: 4145b0f09285735c8d283df157522211b31a44c918b1d10f0a8c622287b690d9
