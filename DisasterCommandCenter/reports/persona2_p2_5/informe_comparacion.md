# Persona 2 — P2.5: comparacion de modelos

Fuente: synthetic_simulation; run_id: dcc_14_4_3_sesion_0001.

Entrenamiento: 324 lecturas de 9 sensores.
Prueba: 108 lecturas de 3 sensores.
Sensores de test: S-E1-02, S-E25-01, S-E30-01.
Semilla: 2026. Particion: sensor_holdout_stratified_by_any_positive.
Features: temperature_c, smoke_index, alarm.

| Conjunto | Target false | Target true | Fraccion mayoritaria |
| --- | ---: | ---: | ---: |
| train | 301 | 23 | 0.929012 |
| test | 85 | 23 | 0.787037 |

## Resultados medidos

| Modelo | Accuracy | Precision | Recall | F1 |
| --- | ---: | ---: | ---: | ---: |
| LogisticRegression | 1.000000 | 1.000000 | 1.000000 | 1.000000 |
| DecisionTreeClassifier | 1.000000 | 1.000000 | 1.000000 | 1.000000 |
| RandomForestClassifier | 0.962963 | 0.851852 | 1.000000 | 0.920000 |
| Clase mayoritaria de train | 0.787037 | 0.000000 | 0.000000 | 0.000000 |

Matrices: filas reales, columnas predichas; orden False, True. Clase positiva: True.

### LogisticRegression

| Real / Predicho | False | True |
| --- | ---: | ---: |
| False | 85 | 0 |
| True | 0 | 23 |

Metricas indefinidas (mostradas como 0): [].

### DecisionTreeClassifier

| Real / Predicho | False | True |
| --- | ---: | ---: |
| False | 85 | 0 |
| True | 0 | 23 |

Metricas indefinidas (mostradas como 0): [].

### RandomForestClassifier

| Real / Predicho | False | True |
| --- | ---: | ---: |
| False | 81 | 4 |
| True | 0 | 23 |

Metricas indefinidas (mostradas como 0): [].

### Clase mayoritaria de train

| Real / Predicho | False | True |
| --- | ---: | ---: |
| False | 85 | 0 |
| True | 23 | 0 |

Metricas indefinidas (mostradas como 0): ['precision'].

## Parametros fijados antes de medir

### LogisticRegression

Preprocesamiento: StandardScaler fitted on train.

~~~json
{
  "C": 1.0,
  "class_weight": "balanced",
  "max_iter": 2000,
  "random_state": 2026,
  "solver": "lbfgs",
  "tol": 0.0001
}
~~~

Avisos de entrenamiento: [].

Convergencia de LR: True.

### DecisionTreeClassifier

Preprocesamiento: none.

~~~json
{
  "class_weight": "balanced",
  "max_depth": 3,
  "min_samples_leaf": 2,
  "random_state": 2026
}
~~~

Avisos de entrenamiento: [].

### RandomForestClassifier

Preprocesamiento: none.

~~~json
{
  "bootstrap": true,
  "class_weight": "balanced",
  "max_depth": 3,
  "max_features": "sqrt",
  "min_samples_leaf": 2,
  "n_estimators": 100,
  "n_jobs": 1,
  "random_state": 2026
}
~~~

Avisos de entrenamiento: [].

## Interpretacion

Comparacion descriptiva sobre el holdout ya observado en P2.4; no hay validacion independiente para elegir un modelo definitivo.

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
- Los tres modelos usan la misma particion y las mismas features.
- LR estandariza solo con train; arbol y bosque reciben las features sin escalar.
- RF usa 100 arboles con n_jobs=1; no hay busqueda de hiperparametros.
- Se reutiliza el holdout de P2.4; las metricas no son una prueba final independiente.
- No se selecciona automaticamente un ganador ni se reentrena con el conjunto completo.

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

El JSON conserva predicciones identificadas de test para cada modelo.
