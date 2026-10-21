# Persona 2 — P2.4: baseline Decision Tree

Fuente: synthetic_simulation; run_id: dcc_14_4_3_sesion_0001.

## Particion por sensores

- Semilla: 2026.
- Entrenamiento: 324 lecturas; sensores: S-E1-01, S-E10-01, S-E10-02, S-E15-01, S-E15-02, S-E25-02, S-E30-02, S-EXT-01, S-EXT-02.
- Prueba: 108 lecturas; sensores: S-E1-02, S-E25-01, S-E30-01.
- Sensores disjuntos, estratificados por presencia de algun positivo.
- Los mismos turnos se observan en ambos conjuntos; el entorno es compartido.

| Conjunto | Target false | Target true | Fraccion mayoritaria |
| --- | ---: | ---: | ---: |
| train | 301 | 23 | 0.929012 |
| test | 85 | 23 | 0.787037 |

## Metricas en sensores reservados

| Referencia | Accuracy | Precision | Recall | F1 |
| --- | ---: | ---: | ---: | ---: |
| Decision Tree | 1.000000 | 1.000000 | 1.000000 | 1.000000 |
| Clase mayoritaria de train | 0.787037 | 0.000000 | 0.000000 | 0.000000 |

Clase positiva: True. Matrices: filas reales, columnas predichas; orden False, True.

### Decision Tree

| Real / Predicho | False | True |
| --- | ---: | ---: |
| False | 85 | 0 |
| True | 0 | 23 |

Metricas indefinidas (mostradas como 0): [].

### Clase mayoritaria

| Real / Predicho | False | True |
| --- | ---: | ---: |
| False | 85 | 0 |
| True | 23 | 0 |

Metricas indefinidas (mostradas como 0): ['precision'].

## Parametros y reglas aprendidas solo en train

{"class_weight": "balanced", "max_depth": 3, "min_samples_leaf": 2, "random_state": 2026}

Features: temperature_c, smoke_index, alarm.

~~~text
|--- temperature_c <= 36.52
|   |--- class: False
|--- temperature_c >  36.52
|   |--- class: True
~~~

## Alcance

- Datos sinteticos de una sola ejecucion; no son sensores fisicos reales.
- Ningun sensor ni lectura se comparte entre entrenamiento y prueba.
- Los turnos y el entorno se comparten; no es una evaluacion de futuro temporal.
- La estratificacion usa presencia de positivos por sensor solo para particionar.
- Los parametros se fijaron antes de medir; no hubo seleccion ni ajuste sobre test.
- No se ha medido generalizacion a otras ejecuciones, incendios o datos reales.
- La temperatura y el target dependen de proximidad al fuego en el generador.
- Un resultado alto puede reflejar esa regla sintetica; no demuestra seguridad operativa.
- La referencia mayoritaria muestra por que accuracy sola no basta.
- Precision, recall y F1 usan True como clase positiva; divisiones indefinidas valen 0.

## Reproducibilidad

Python: 3.13.7.
- scikit-learn==1.9.1
- numpy==2.5.4
- scipy==1.18.1
- joblib==1.6.0
- threadpoolctl==3.7.0
- narwhals==2.27.1
- cloudpickle==3.1.2

SHA-256 del paquete:

- lecturas_sensores.csv: c8c6c1efae51824bedf876ddd94e67519db59224867d84fb4b5bf71761ea652b
- lecturas_sensores.jsonl: dd3ba0b935f796a1e72cc0ab4715884c1ae42a2c50b7d0e29890e5e9b784a480
- manifiesto_sensores.json: 4145b0f09285735c8d283df157522211b31a44c918b1d10f0a8c622287b690d9

El JSON incluye las predicciones de test y sus claves para auditoria.
