# Persona 2 — P2.1 a P2.7: datos, IA e integración

Rama de trabajo: persona2-datos-ia. Esta fase consume el contrato 1.0 de
Persona 1. Los datos son sintéticos, no lecturas de dispositivos reales.
Los turnos no son segundos ni fechas.

## Archivos y uso

- src/persona2/ingestion.py: entrada de Persona 2.
- test_persona2_ingestion.py: pruebas con exportaciones reales del simulador
  y paquetes alterados únicamente en directorios temporales.
- src/integration/persona2_contract_15_1.py: lector y reglas existentes que
  se reutilizan sin modificaciones.

Con DisasterCommandCenter/src en sys.path (o en PYTHONPATH):

~~~python
from persona2.ingestion import read_sensor_package

package = read_sensor_package("exports/ejemplo_persona2")
observables = package["observables"]
labelled_rows = package["labelled_rows"]
manifest = package["manifest"]
~~~

La carpeta debe contener lecturas_sensores.csv, lecturas_sensores.jsonl y
manifiesto_sensores.json. Se propagan los ValueError del contrato y no se
corrigen ni completan datos. La configuración de sensores del proyecto se
usa por defecto mediante una ruta absoluta calculada desde el módulo.
Puede indicarse otra configuración confiable con sensors_path="ruta/sensores.json";
la configuración no se toma del paquete recibido.

La salida conserva los nombres del contrato. observables excluye
fire_within_2_cells. labelled_rows conserva esa etiqueta booleana de
verdad-terreno: fuego activo a distancia Manhattan de hasta dos celdas en
el turno actual. No debe usarse como feature. P2.1 no construye todavía X/y
ni selecciona features; los identificadores y metadatos observables no se
convierten automáticamente en entradas de un modelo.

## Validación delegada al contrato

Se comprueban campos exactos, tipos, valores finitos, rangos, identidad y
ubicación contra la configuración, ejecución única, duplicados por
turn/sensor_id, turnos consecutivos, sensores completos por turno,
correspondencia CSV/JSONL y conteos y procedencia del manifiesto.

Los campos obligatorios son schema_version, run_id, turn, sensor_id, x, y,
building_id, temperature_c, smoke_index, alarm y fire_within_2_cells.
Solo building_id admite None (sensor exterior); en CSV se representa vacío.

- schema_version: "1.0".
- run_id: texto no vacío, igual al manifiesto.
- sensor_id: texto no vacío, perteneciente a la configuración.
- turn: entero no negativo; x: entero 0..159; y: entero 0..99.
- building_id: texto no vacío o None, coincidente con la configuración.
- temperature_c: int/float finito entre -50 y 500, sin aceptar bool.
- smoke_index: int/float finito entre 0 y 1, sin aceptar bool.
- alarm y fire_within_2_cells: bool estricto.

La validación no verifica de nuevo la física del simulador ni recalcula
alarm a partir de las mediciones: sus umbrales son configurables.
No exige siempre 432 lecturas; acepta otros intervalos completos válidos.
El ejemplo de entrega tiene 12 sensores y turnos 0..35: 432 lecturas.

## Generar y probar

Desde la raíz del repositorio, utilizando el entorno virtual existente:

~~~powershell
# Sin --salida, el ejemplo se genera, valida y elimina en una carpeta temporal.
.\.venv\Scripts\python.exe -B DisasterCommandCenter/generar_entrega_persona2_15_1.py

# Guardar un ejemplo para consumirlo después.
.\.venv\Scripts\python.exe -B DisasterCommandCenter/generar_entrega_persona2_15_1.py --salida exports/ejemplo_persona2

# Pruebas nuevas y regresiones directamente relacionadas.
.\.venv\Scripts\python.exe -B DisasterCommandCenter/test_persona2_ingestion.py
.\.venv\Scripts\python.exe -B DisasterCommandCenter/test_entrega_persona2_15_1.py
.\.venv\Scripts\python.exe -B DisasterCommandCenter/test_sensores.py

# Ejemplo de consumo desde la raíz del repositorio.
$env:PYTHONPATH = (Resolve-Path DisasterCommandCenter/src).Path
.\.venv\Scripts\python.exe -B -c "from persona2.ingestion import read_sensor_package; print(len(read_sensor_package('exports/ejemplo_persona2')['observables']))"
~~~

Resultado esperado: 19 pruebas nuevas aprobadas; las pruebas existentes de
entrega y sensores aprobadas; 432 observaciones en el ejemplo.
Las pruebas de tipos y rangos alteran CSV y JSONL coherentemente para
alcanzar esas validaciones, sin confundirlas con divergencias de formato.

La recepción solo necesita la biblioteca estándar. No añade dependencias,
almacenamiento, modelos de IA ni acoplamiento a Pygame. La generación del
ejemplo y las pruebas de integración sí utilizan el simulador existente.

## Trabajo local anterior en Chagoya

El pipeline de Chagoya solicita campos que esta exportación no proporciona
(por ejemplo timestamp, co, fire_intensity, occupancy y distance_to_fire).
P2.1 no lo modifica ni inventa valores para adaptarlo. Su integración
requiere una decisión posterior sobre esos contratos.

## P2.2 — Dataset tabular

src/persona2/dataset.py ofrece load_sensor_dataset(folder, *, sensors_path=...).
Primero usa la recepción de P2.1 y después crea un SensorDataset con tres
tablas alineadas en memoria. No modifica archivos ni añade dependencias.

~~~python
from persona2.dataset import load_sensor_dataset

dataset = load_sensor_dataset("exports/ejemplo_persona2")
X = dataset.X
y = dataset.y
print(dataset.feature_columns)  # ("temperature_c", "smoke_index", "alarm")
print(len(X), len(y))  # 432, 432 para el ejemplo generado
~~~

| Salida | Columnas o contenido |
| --- | --- |
| feature_columns / X | temperature_c, smoke_index, alarm |
| target_column / y | fire_within_2_cells |
| metadata_columns / metadata_rows | schema_version, run_id, turn, sensor_id, x, y, building_id |
| manifest | Procedencia sintética, conteos y notas originales |

Cada tabla es una tupla de filas y cada fila de X y metadata_rows es una
tupla. X[i], y[i] y metadata_rows[i] pertenecen a la misma observación; no se
ordena ni se filtra ninguna tabla por separado. Los nombres de columnas
definen su orden. La representación evita cambios en las matrices en el
sitio; el diccionario manifest sigue siendo un diccionario normal.

X contiene mediciones float y alarm como int 0/1, sin imputación,
normalización ni redondeo adicional. y mantiene bool. Los metadatos
conservan los valores originales, incluido building_id=None en exteriores.
Los paquetes válidos con otros números de turnos se aceptan sin rellenar
filas; 432 es el tamaño del ejemplo, no una restricción de P2.2.

Las features se extraen únicamente de observables y mediante una selección
explícita. Nunca se utiliza la fila completa como X. Un control rechaza el
target en FEATURE_COLUMNS y campos ajenos al contrato observable.
Las pruebas cambian solo las etiquetas y comprueban que X permanezca igual.

Identificadores, turno y ubicación quedan fuera de X para mantenerlos
disponibles para trazabilidad y futuras particiones de entrenamiento/prueba,
sin introducirlos por defecto como atajos asociados a este escenario.
alarm es una señal observable derivada de umbrales de temperatura/humo,
no el target; su redundancia se deberá evaluar más adelante.

Esta fase no entrena modelos, no calcula estadísticas exploratorias ni
separa entrenamiento/prueba. El análisis exploratorio corresponde a P2.3
y el baseline a P2.4.

Desde la raíz del repositorio:

~~~powershell
.\.venv\Scripts\python.exe -B DisasterCommandCenter/test_persona2_dataset.py
.\.venv\Scripts\python.exe -B DisasterCommandCenter/test_persona2_ingestion.py
.\.venv\Scripts\python.exe -B DisasterCommandCenter/test_entrega_persona2_15_1.py
~~~

Resultado esperado: 13 pruebas de dataset aprobadas, además de las de P2.1
y entrega. Incluyen anti-leakage, alineación tras reordenar el paquete,
tipos numéricos, metadatos nulos, procedencia y rechazo de paquetes inválidos.

## P2.3 — Análisis exploratorio reproducible

src/persona2/eda.py calcula el análisis de un paquete mediante P2.2, sin
modificarlo ni entrenar modelos. Usa solo la biblioteca estándar.

~~~python
from persona2.eda import analyze_sensor_package, render_report

report = analyze_sensor_package("exports/ejemplo_persona2")
print(report["target"])
markdown = render_report(report)
~~~

El informe contiene:

- Registros, sensores, turnos, cobertura por sensor y turno.
- Rol, tipos observados, cardinalidad y nulos de las once columnas.
- Conteos y proporciones de ambas clases del target y de alarm.
- Distribución del target por sensor.
- Mínimo, máximo, media, mediana y desviación estándar poblacional
  (ddof=0) para temperature_c y smoke_index.
- Procedencia sintética y SHA-256 de los tres archivos del paquete.

Los tipos corresponden a la representación preparada por P2.2, no a los
textos del CSV: temperatura/humo float, alarm int 0/1, target bool.
building_id=None se cuenta como nulo permitido de un sensor exterior.
Las ausencias en campos obligatorios provocan un rechazo por P2.1; por
tanto, cero ausencias en este informe describe únicamente datos validados,
no un escaneo tolerante de archivos corruptos.

La señal de desbalance usa una regla descriptiva explícita: una clase con
al menos 80% de las observaciones. Se informa también si existe una sola
clase. Los conteos y proporciones están disponibles para interpretar el
resultado sin depender de ese umbral.

### Generar el informe desde la raíz del repositorio

~~~powershell
.\.venv\Scripts\python.exe -B DisasterCommandCenter/generar_entrega_persona2_15_1.py --salida exports/ejemplo_persona2
$env:PYTHONPATH = (Resolve-Path DisasterCommandCenter/src).Path
.\.venv\Scripts\python.exe -B -m persona2.eda exports/ejemplo_persona2 --output-dir DisasterCommandCenter/reports/persona2_p2_3
~~~

La CLI imprime JSON. Sin --output-dir no escribe archivos. Con esa opción
guarda informe_eda.json e informe_eda.md; el JSON conserva la precisión de
los cálculos y Markdown redondea solo para presentación.
--sensors-path permite indicar una configuración confiable distinta.

Los informes locales en reports/persona2_p2_3/ se generaron con produce
de generar_entrega_persona2_15_1.py y el analizador, usando un paquete
temporal. Sus hashes identifican los archivos analizados; los comandos
anteriores permiten regenerar el ejemplo y el informe.

### Pruebas y alcance

~~~powershell
.\.venv\Scripts\python.exe -B DisasterCommandCenter/test_persona2_eda.py
.\.venv\Scripts\python.exe -B DisasterCommandCenter/test_persona2_dataset.py
.\.venv\Scripts\python.exe -B DisasterCommandCenter/test_persona2_ingestion.py
.\.venv\Scripts\python.exe -B DisasterCommandCenter/test_entrega_persona2_15_1.py
~~~

Resultado esperado: 16 pruebas de EDA, 13 de dataset y 19 de recepción
aprobadas, además de la entrega. La prueba de EDA usa un paquete sintético
pequeño con estadísticas conocidas, verifica las clases únicas y el límite
de 80%, y analiza también el ejemplo generado realmente por Persona 1.
Comprueba que los cambios en etiquetas no afecten los perfiles de features
ni las estadísticas de mediciones.

El informe describe una ejecución sintética. Lecturas del mismo sensor y
turnos próximos están relacionadas; no deben tratarse automáticamente
como ejemplos independientes al diseñar la evaluación posterior.
El desbalance impide justificar un modelo únicamente por accuracy.
La partición, el entrenamiento y las métricas de predicción quedan para
P2.4, sujeto a confirmación.

### Resultados calculados del ejemplo de Persona 1

La regla existente de .gitignore excluye reports/. Los informes completos
permanecen como artefactos locales regenerables; este resumen conserva
los resultados principales junto al código. Los valores siguientes se
extrajeron del JSON producido por el analizador, sin entrenar modelos.

| Medida | Resultado |
| --- | ---: |
| Lecturas | 432 |
| Sensores | 12 |
| Turnos | 36 (0–35) |
| Ausencias obligatorias en datos validados | 0 |
| Nulos permitidos en building_id | 72 |
| Target false | 386 (89.35%) |
| Target true | 46 (10.65%) |
| Sensores con positivos | 3 |
| Alarma activa | 126 |

| Variable | Mínimo | Máximo | Media | Mediana | Desv. poblacional |
| --- | ---: | ---: | ---: | ---: | ---: |
| temperature_c | 23.852000 | 109.137000 | 29.589296 | 24.014000 | 17.971957 |
| smoke_index | 0.000000 | 1.000000 | 0.165050 | 0.002045 | 0.275682 |

Hay desbalance de clases en este ejemplo sintético y los positivos se
concentran en pocos sensores. Esto limita lo que podrá concluirse de
una evaluación sobre esta única ejecución. P2.4 deberá explicitar la
partición y reportar precision, recall, F1 y matriz de confusión, además
de accuracy; P2.3 no ha realizado ese entrenamiento.

## P2.4 — Baseline Decision Tree

src/persona2/baseline.py entrena un DecisionTreeClassifier de referencia y
devuelve un informe de evaluación. Consume load_sensor_dataset de P2.2 y
no modifica simulación, integración, contratos ni el dataset recibido.
No guarda un modelo ni implementa aún una interfaz de predicción en vivo.

### Dependencias opcionales de IA

El entorno virtual usado contiene Python 3.13.7. La instalación se separa
de requirements.txt de Persona 1:

~~~powershell
.\.venv\Scripts\python.exe -m pip install -r DisasterCommandCenter/requirements-persona2-ml.txt
~~~

scikit-learn 1.9.1 aporta el árbol, la partición estratificada y las métricas
estándar. Evita implementar un algoritmo de entrenamiento propio.
requirements-persona2-ml.txt fija también las versiones transitivas usadas:

- NumPy y SciPy: estructuras y operaciones numéricas de scikit-learn.
- joblib y cloudpickle: utilidades internas de cómputo y serialización.
- threadpoolctl: control de hilos de bibliotecas numéricas.
- narwhals: compatibilidad de estructuras tabulares usada por la biblioteca.

Estas dependencias afectan al entorno .venv y se importan únicamente al
usar baseline.py, model_comparison.py, inference.py o sus pruebas. P2.1, P2.2, P2.3 y el simulador no importan
el baseline. No se modifica el archivo de dependencias de Persona 1.

Fuentes: [DecisionTreeClassifier](https://scikit-learn.org/stable/modules/generated/sklearn.tree.DecisionTreeClassifier.html),
[distribución de scikit-learn](https://pypi.org/project/scikit-learn/1.9.1/).

### Protocolo fijado antes de medir

- Features: temperature_c, smoke_index y alarm, sin target ni metadatos.
- Se reserva 25% de los sensores completos para prueba y 75% para entrenamiento.
- Se ordenan los identificadores y se estratifican sensores por presencia de
  algún positivo, con random_state=2026. Los conteos de ambas clases por
  conjunto se reportan; la proporción de lecturas positivas no se fija.
- Ningún sensor ni lectura pertenece a ambos conjuntos. El entorno y los
  turnos sí se comparten: la prueba mide sensores reservados en la misma
  ejecución, no predicción de turnos futuros.
- El árbol usa max_depth=3, min_samples_leaf=2 y class_weight="balanced".
  Los pesos se calculan en fit exclusivamente con las etiquetas de train.
  La semilla del árbol también es 2026. No hay búsqueda de hiperparámetros.
- La referencia DummyClassifier predice siempre la clase mayoritaria de
  entrenamiento; contextualiza accuracy sin comparar todavía otros
  modelos de IA como los previstos para P2.5.
- Se mide una vez en test, sin reajustar el árbol ni escoger parámetros
  según sus resultados.

El examen de las etiquetas del ejemplo mostró positivos solo en turnos
0..22. Reservar el último 30% de turnos dejaría test sin positivos.
Por eso este baseline usa la partición por sensores indicada, no cambia
su corte temporal hasta lograr una métrica favorable. La estratificación
usa las etiquetas únicamente para formar los grupos, nunca como features.
Esta decisión y las limitaciones del escenario se declaran antes del
entrenamiento.

split_by_sensor rechaza datos con una sola clase o sin al menos dos
sensores con positivos y dos sin positivos. También rechaza una fracción
que no permita representar ambos estratos. No cae silenciosamente en
una separación aleatoria por filas.

### Ejecutar y auditar

Desde la raíz del repositorio, tras instalar las dependencias opcionales:

~~~powershell
.\.venv\Scripts\python.exe -B DisasterCommandCenter/generar_entrega_persona2_15_1.py --salida exports/ejemplo_persona2
$env:PYTHONPATH = (Resolve-Path DisasterCommandCenter/src).Path
.\.venv\Scripts\python.exe -B -m persona2.baseline exports/ejemplo_persona2 --output-dir DisasterCommandCenter/reports/persona2_p2_4
.\.venv\Scripts\python.exe -B DisasterCommandCenter/test_persona2_baseline.py
~~~

Sin --output-dir, la CLI solo imprime el JSON. Con esa opción guarda
informe_baseline.json e informe_baseline.md. --sensors-path acepta una
configuración confiable alternativa. Los informes completos se generaron
con el ejemplo real del programa, mediante un paquete temporal; reports/
permanece ignorado por Git como estaba configurado.

~~~python
from persona2.baseline import evaluate_baseline

report = evaluate_baseline("exports/ejemplo_persona2")
print(report["metrics"])
~~~

La matriz de confusión fija el orden False, True en ambos ejes:
filas = etiqueta real, columnas = predicción; [[TN, FP], [FN, TP]].
Precision, recall y F1 corresponden a la clase positiva True. Una división
indefinida devuelve 0 y se declara en undefined_metrics; no se oculta.

El JSON incluye hashes del paquete, versiones efectivas, parámetros,
sensores de cada conjunto, distribución de clases, reglas del árbol y las
predicciones de test identificadas por run_id, turn y sensor_id.

Las 19 pruebas nuevas verifican separación, reproducibilidad, entrenamiento
solo con train, exclusión del target, métricas de casos conocidos,
predicciones auditables y generación de informes. Las divisiones
indefinidas y la falta de grupos/clases tienen pruebas específicas.

### Resultados medidos en el ejemplo sintético

Entrenamiento: 324 lecturas de 9 sensores.
Prueba: 108 lecturas de 3 sensores.
Sensores de prueba: S-E1-02, S-E25-01, S-E30-01.

| Conjunto | Target false | Target true |
| --- | ---: | ---: |
| train | 301 | 23 |
| test | 85 | 23 |

| Referencia | Accuracy | Precision | Recall | F1 |
| --- | ---: | ---: | ---: | ---: |
| Decision Tree | 1.000000 | 1.000000 | 1.000000 | 1.000000 |
| Mayoritaria de train | 0.787037 | 0.000000 | 0.000000 | 0.000000 |

Matriz del árbol: [[85, 0], [0, 23]].
Matriz de la referencia: [[85, 0], [23, 0]].

Regla aprendida exclusivamente con train:

~~~text
|--- temperature_c <= 36.52
|   |--- class: False
|--- temperature_c >  36.52
|   |--- class: True
~~~

El resultado perfecto no demuestra generalización: temperatura y target
dependen de la misma proximidad sintética al fuego. La evaluación comparte
entorno y turnos, y todos los positivos de test pertenecen a un solo
sensor. Es un baseline verificable del ejemplo, no evidencia de desempeño
en incendios nuevos ni mediciones físicas. El desbalance de entrenamiento
y el recall nulo de la referencia muestran por qué accuracy sola no basta.

La comparación de modelos se documenta a continuación en P2.5.

## P2.5 — Comparación descriptiva de modelos

src/persona2/model_comparison.py reutiliza evaluate_baseline de P2.4:
conserva su Decision Tree, referencia mayoritaria, partición, métricas y
metadatos. Añade Logistic Regression y Random Forest sobre las mismas
features y los mismos sensores de entrenamiento y prueba. No modifica
baseline.py ni introduce dependencias nuevas.

El archivo requirements-persona2-ml.txt de P2.4 sigue siendo suficiente.
P2.1–P2.3 y el simulador no importan estos modelos.

### Parámetros fijados antes de evaluar

| Modelo | Preparación y parámetros |
| --- | --- |
| Logistic Regression | Pipeline con StandardScaler; solver=lbfgs, C=1, class_weight=balanced, max_iter=2000, tol=0.0001, random_state=2026 |
| Decision Tree | Baseline sin cambios: max_depth=3, min_samples_leaf=2, class_weight=balanced, random_state=2026 |
| Random Forest | 100 árboles; max_depth=3, min_samples_leaf=2, max_features=sqrt, bootstrap=True, class_weight=balanced, n_jobs=1, random_state=2026 |

El escalador aprende media y escala solo de train, dentro del Pipeline;
test se transforma con esos mismos valores. Árbol y bosque reciben las
features sin escalar. Los tres modelos usan temperature_c, smoke_index
y alarm; fire_within_2_cells permanece únicamente como target.

Fuente sobre el escalado dentro de Pipeline:
[preprocesamiento de scikit-learn](https://scikit-learn.org/stable/modules/preprocessing.html#standardization-or-mean-removal-and-variance-scaling).
Documentación de los modelos:
[LogisticRegression](https://scikit-learn.org/stable/modules/generated/sklearn.linear_model.LogisticRegression.html),
[RandomForestClassifier](https://scikit-learn.org/stable/modules/generated/sklearn.ensemble.RandomForestClassifier.html).

No se buscan hiperparámetros ni se ajustan umbrales sobre test. Los avisos
de entrenamiento se conservan en fit_warnings. Una advertencia de
convergencia queda reflejada en diagnostics.converged; no se oculta.

### Ejecutar y reproducir

Desde la raíz del repositorio, con las dependencias opcionales de P2.4:

~~~powershell
.\.venv\Scripts\python.exe -B DisasterCommandCenter/generar_entrega_persona2_15_1.py --salida exports/ejemplo_persona2
$env:PYTHONPATH = (Resolve-Path DisasterCommandCenter/src).Path
.\.venv\Scripts\python.exe -B -m persona2.model_comparison exports/ejemplo_persona2 --output-dir DisasterCommandCenter/reports/persona2_p2_5
.\.venv\Scripts\python.exe -B DisasterCommandCenter/test_persona2_model_comparison.py
~~~

~~~python
from persona2.model_comparison import compare_models

report = compare_models("exports/ejemplo_persona2")
for name, model in report["models"].items():
    print(name, model["metrics"])
~~~

Sin --output-dir la CLI solo imprime el JSON. Con esa opción guarda
informe_comparacion.json e informe_comparacion.md. --sensors-path permite
indicar una configuración confiable alternativa.

El informe conserva métricas, matrices de confusión, parámetros, versiones,
hashes del paquete y predicciones identificadas de test para cada modelo.
La matriz sigue el orden [[TN, FP], [FN, TP]], con True como clase positiva.
Las divisiones indefinidas se registran y toman valor 0 como en P2.4.

Los informes locales se generaron a partir de produce del generador
original. reports/ permanece ignorado por Git; el resumen siguiente se
extrae del JSON generado para conservar también sus resultados en Git.

### Alcance y pruebas

El conjunto de prueba ya fue inspeccionado en P2.4. P2.5 reutiliza ese
holdout con fines descriptivos: no es una prueba final independiente.
Los sensores son disjuntos, pero los turnos y el entorno se comparten.
Los resultados no miden generalización a nuevas ejecuciones, incendios
o sensores físicos. Las etiquetas y la temperatura comparten una regla
sintética de proximidad al fuego.

El informe no selecciona automáticamente un ganador; selected_model es
None. La comparación no guarda ni despliega un modelo.

Las 16 pruebas nuevas verifican:

- Las mismas filas, features y etiquetas para los tres modelos.
- Fit de LR/RF solo sobre train y predicciones sobre el mismo test.
- Media y escala aprendidas únicamente de entrenamiento.
- Cambios en las features de test sin cambios en los ajustes aprendidos.
- Coincidencia del Decision Tree y referencia con P2.4.
- Matrices auditables, reproducibilidad y conservación del paquete.
- Rechazo del target en X y de paquetes alterados entre lecturas.
- Registro de avisos de convergencia y generación de JSON/Markdown.

### Resultados medidos del ejemplo sintético

Train: 324 lecturas de 9 sensores.
Test: 108 lecturas de 3 sensores.
Sensores de test: S-E1-02, S-E25-01, S-E30-01.

| Modelo | Accuracy | Precision | Recall | F1 |
| --- | ---: | ---: | ---: | ---: |
| LogisticRegression | 1.000000 | 1.000000 | 1.000000 | 1.000000 |
| DecisionTreeClassifier | 1.000000 | 1.000000 | 1.000000 | 1.000000 |
| RandomForestClassifier | 0.962963 | 0.851852 | 1.000000 | 0.920000 |
| Mayoritaria de train | 0.787037 | 0.000000 | 0.000000 | 0.000000 |

Matrices obtenidas:

- LogisticRegression: [[85, 0], [0, 23]].
- DecisionTreeClassifier: [[85, 0], [0, 23]].
- RandomForestClassifier: [[81, 4], [0, 23]].
- Mayoritaria de train: [[85, 0], [23, 0]].

Logistic Regression convergió en 13 iteraciones.
Random Forest produjo 4 falsos positivos y 0 falsos negativos en este test.
En este ejemplo, el bosque no mejora las métricas del árbol simple.
Este resultado no establece qué modelo generaliza mejor fuera del escenario.

P2.6 y P2.7 se implementan en las secciones siguientes.

## P2.6 — Persistencia PostgreSQL

Archivos propios:

- src/persona2/postgres_repository.py: acceso a datos y CLI.
- src/persona2/sql/001_initial.sql: esquema inicial, separado de la simulación.
- requirements-persona2-db.txt: dependencias opcionales de base de datos.
- .env.example: nombres de variables y valores de ejemplo, sin credenciales reales.
- tools/postgres_test_server.py: clúster temporal exclusivo para pruebas.
- test_persona2_postgres.py: 15 pruebas, con PostgreSQL real cuando está disponible.

El esquema por defecto es persona2. initialize crea solo ese esquema y sus
tablas si faltan. Es el esquema inicial 001; futuros cambios estructurales
necesitarán una migración nueva, no reemplazar silenciosamente tablas.

| Tabla | Contenido y claves |
| --- | --- |
| simulations | run_id, manifiesto sintético, versión, hash canónico y política de muestreo |
| sensors | Identidad y ubicación por run_id/sensor_id |
| readings | Mediciones y target separado, clave run_id/turn/sensor_id |
| events | Un sensor_alarm por lectura con alarm=True; no equivale a una transición de estado |
| models | model_id y metadatos de entrenamiento/versionado |
| predictions | Predicción por run_id/turn/sensor_id/model_id, con FK a la lectura y al modelo |
| reports | Resultados EDA, baseline, comparación e integración, con identificador por contenido |

Las importaciones pasan primero por read_sensor_package de P2.1. Una
escritura completa confirma su transacción al terminar y hace rollback
si falla. El mismo paquete y política con igual run_id son idempotentes.
Un run_id con contenido o política diferentes produce ValueError, sin
sobrescribir el anterior. Los valores se envían como parámetros de SQL
y los identificadores de esquema se componen con psycopg.sql.Identifier.

Los run_id del ejemplo de Persona 1 son identificadores de sesión locales,
no UUID globales. Para simulaciones realmente distintas el origen deberá
proporcionar IDs distintos; el repositorio detecta colisiones y no renombra
ni altera automáticamente datos de Persona 1.

Por defecto se guardan las lecturas exportadas por turno, no los frames de
Pygame. every_n_turns permite reducir su frecuencia, conservando siempre
alarmas y los turnos inicial/final. El manifiesto mantiene el número de
registros original y la respuesta informa stored_readings por separado.
Un conjunto muestreado no se presenta como el dataset completo para
entrenamiento. Las predicciones solo pueden referenciar lecturas guardadas;
la demostración integrada usa every_n_turns=1.

readings(run_id) devuelve las once columnas del contrato, incluida
schema_version y el target. Antes de inferir se debe usar el gateway para
extraer observables, o eliminar explícitamente el target mediante
OBSERVABLE_FIELDS. Nunca pasar directamente una fila etiquetada al servicio.

### Dependencia y configuración

~~~powershell
.\.venv\Scripts\python.exe -m pip install -r DisasterCommandCenter/requirements-persona2-db.txt
$env:DCC_DATABASE_URL = "postgresql://dcc_user:CHANGE_ME@127.0.0.1:5432/disaster_command_center"
~~~

Sustituye los valores del ejemplo por una base y rol existentes donde puedas
crear el esquema de Persona 2. Los scripts leen las variables del proceso;
no cargan archivos .env automáticamente. DCC_DATABASE_URL no se imprime ni
se guarda en informes. .env está ignorado por Git.

psycopg[binary]==3.3.6 es el controlador PostgreSQL. Su extra binary incluye
las bibliotecas cliente necesarias sin compilación local; tzdata==2026.5
fija la dependencia de zonas horarias usada en Windows. Solo se requiere al
importar el repositorio o ejecutar sus pruebas. No cambia requirements.txt
de Persona 1, las dependencias de IA ni los motores.

Fuentes: [instalación de Psycopg](https://www.psycopg.org/psycopg3/docs/basic/install.html),
[transacciones](https://www.psycopg.org/psycopg3/docs/basic/transactions.html),
[PostgreSQL para Windows](https://www.postgresql.org/download/windows/).

### Importar y consultar

~~~powershell
$env:PYTHONPATH = (Resolve-Path DisasterCommandCenter/src).Path
.\.venv\Scripts\python.exe -B -m persona2.postgres_repository exports/ejemplo_persona2
# Ejemplo de muestreo en un esquema distinto para no cambiar la política anterior:
.\.venv\Scripts\python.exe -B -m persona2.postgres_repository exports/ejemplo_persona2 --schema persona2_muestreo --every-n-turns 5
~~~

~~~python
from persona2.postgres_repository import PostgresRepository

repository = PostgresRepository()  # Lee DCC_DATABASE_URL.
repository.initialize()
imported = repository.import_package("exports/ejemplo_persona2")
rows = repository.readings(imported["run_id"])
print(repository.counts(imported["run_id"]))

# report es el dict devuelto por EDA, baseline o comparación:
# repository.save_report(imported["run_id"], "comparison", report)
~~~

register_model registra metadatos inmutables por model_id. save_predictions
valida y guarda un lote atómicamente: repetir el mismo resultado no duplica,
pero cambiar una predicción existente requiere otro model_id. Una FK
faltante o un conflicto hace rollback de todo el lote.

## P2.7 — Interfaz de predicción e integración externa

Archivos propios:

- src/persona2/observations.py: valida una observación sin etiqueta.
- src/persona2/inference.py: PredictionService y entrenamiento explícito de referencia.
- src/integration/persona2_gateway.py: puente para lecturas existentes, sin Pygame/IA/DB.
- demo_persona2_integracion.py: escena original, predicción por turno y persistencia opcional.
- tools/verify_persona2.py: verificación reproducible con PostgreSQL real.
- test_persona2_inference.py: 16 pruebas de observaciones y servicio.
- test_persona2_gateway.py: 10 pruebas del puente y su control de turnos.
- test_persona2_end_to_end.py: 6 pruebas de la cadena completa y roundtrip por PostgreSQL.

El lector de Persona 1 valida paquetes completos etiquetados. No ofrece
un validador público para una sola observación en vivo. ObservationProcessor
cubre ese caso usando OBSERVABLE_FIELDS, SCHEMA_VERSION y los mismos tipos,
rangos y configuración; evita cambiar los archivos de Persona 1.

### Entrada y salida

El servicio recibe exactamente las diez columnas de OBSERVABLE_FIELDS.
Rechaza fire_within_2_cells incluso si su valor fuera None. Valida todo el
lote antes de llamar al modelo y rechaza duplicados por run_id/turn/sensor_id.

Las únicas features siguen siendo temperature_c, smoke_index y alarm.
La interfaz predict(observation) devuelve un dict con:

- schema_version="1.0", dataset_kind="synthetic_simulation".
- run_id, turn, sensor_id, x, y, building_id de la observación.
- model_id reproducible y target_name="fire_within_2_cells".
- predicted_fire_within_2_cells como bool.

La salida representa presencia estimada de fuego a distancia Manhattan
de hasta dos celdas en el turno actual. No es pronóstico temporal, nivel
general de riesgo ni declaración de zona segura.

~~~python
from persona2.ingestion import read_sensor_package
from persona2.inference import train_prediction_service

package = read_sensor_package("exports/ejemplo_persona2")
service = train_prediction_service("exports/ejemplo_persona2")
prediction = service.predict(package["observables"][0])
predictions = service.predict_many(package["observables"][:12])
~~~

train_prediction_service usa explícitamente el Decision Tree experimental
de P2.4, ajustado solo con sus 324 lecturas de entrenamiento. No elige
automáticamente un ganador de P2.5 ni reentrena con test. El ID combina
contenido de entrenamiento, parámetros y versión de scikit-learn.

PredictionService también acepta un predictor ya ajustado con predict(X)
que devuelva un bool por fila, más model_id y metadatos compatibles.
Eso permite sustituir el modelo conservando la interfaz para Persona 1/3.
No se serializan objetos ejecutables ni se cargan modelos externos;
la referencia se reconstruye explícitamente desde el paquete validado.
La tabla models guarda sus metadatos, no el objeto Python.

### Conectar una escena existente

~~~python
from integration.persona2_gateway import SensorPredictionAdapter

adapter = SensorPredictionAdapter(service)

# El llamador conserva el control habitual de la escena.
scene.start()
new_predictions = adapter.update(scene)
scene.step()
new_predictions = adapter.update(scene)
~~~

El gateway acepta current_readings con el contrato original (incluida su
etiqueta sintética), copia solo OBSERVABLE_FIELDS y entrega esos observables
al servicio. Una etiqueta distinta no puede cambiar su entrada de features.
Para una lista independiente se ofrece predict_sensor_readings(service, rows).

El adaptador procesa un turno una sola vez; una pausa sin muestras nuevas
devuelve []. Un turno repetido con mediciones modificadas o un retroceso
con el mismo run_id produce ValueError. Una nueva ejecución puede empezar
en turno 0 con otro run_id; ante reinicios que reutilicen el mismo ID se
debe crear un adaptador nuevo.

El gateway no importa Pygame, scikit-learn ni psycopg. La inferencia no
importa Pygame, motores ni PostgreSQL. Solo la demostración importa la
escena para ejercitar el circuito. No cambia rutas, estado de personas ni
alarmas existentes de Persona 1. La persistencia se invoca explícitamente
fuera de los frames, tras exportar un paquete.

### Demostración ejecutable

Desde la raíz, con dependencias de IA instaladas:

~~~powershell
.\.venv\Scripts\python.exe -B DisasterCommandCenter/demo_persona2_integracion.py --output-dir DisasterCommandCenter/reports/persona2_p2_7
# Con un servidor ya configurado en DCC_DATABASE_URL:
.\.venv\Scripts\python.exe -B DisasterCommandCenter/demo_persona2_integracion.py --persist --output-dir DisasterCommandCenter/reports/persona2_p2_7
~~~

Sin --training-package genera un ejemplo temporal con el generador original.
La escena avanza 35 turnos después del muestreo inicial, prueba una pausa y
genera 432 predicciones. --training-package permite usar otro paquete.
--persist registra paquete, metadatos del modelo, predicciones e informe.
No mide calidad predictiva: comparte escenario con el ejemplo de entrenamiento.

### Pruebas PostgreSQL y verificación completa

Se requiere una de estas dos opciones:

- DCC_POSTGRES_BIN: directorio con initdb y pg_ctl de PostgreSQL.
  Las pruebas crean un clúster propio en un directorio temporal, con
  contraseña aleatoria, autenticación SCRAM y escucha solo en 127.0.0.1.
  Al terminar lo detienen y eliminan. No instalan servicios.
- DCC_TEST_DATABASE_URL: conexión explícita a una base de pruebas donde
  puedan crearse esquemas. Los tests usan esquemas UUID exclusivos y solo
  eliminan esos esquemas. El verificador usa dcc_p2_verification.

~~~powershell
# Sustituye por tu directorio de binarios:
$env:DCC_POSTGRES_BIN = "C:\Program Files\PostgreSQL\18\bin"
.\.venv\Scripts\python.exe -B DisasterCommandCenter/test_persona2_postgres.py
.\.venv\Scripts\python.exe -B DisasterCommandCenter/test_persona2_inference.py
.\.venv\Scripts\python.exe -B DisasterCommandCenter/test_persona2_gateway.py
.\.venv\Scripts\python.exe -B DisasterCommandCenter/test_persona2_end_to_end.py
.\.venv\Scripts\python.exe -B DisasterCommandCenter/tools/verify_persona2.py
~~~

En esta máquina se descargaron binarios oficiales EDB PostgreSQL 18.4 en
un directorio temporal, sin instalar servicios. La ubicación está en el
archivo local ignorado reports/persona2_p2_6/runtime_location.txt. Mientras
exista ese runtime puede reutilizarse así:

~~~powershell
$pgRuntime = (Get-Content DisasterCommandCenter/reports/persona2_p2_6/runtime_location.txt -Raw).Trim()
$env:DCC_POSTGRES_BIN = Join-Path $pgRuntime "pgsql/bin"
.\.venv\Scripts\python.exe -B DisasterCommandCenter/tools/verify_persona2.py
~~~

Sin servidor/binarios configurados, los tests PostgreSQL se marcan como
omitidos, no como una verificación real aprobada. La evidencia siguiente
sí se obtuvo con PostgreSQL real. Un servidor permanente se configura
mediante DCC_DATABASE_URL; las pruebas no dejan una base persistente activa.

### Evidencia obtenida en la comprobación integral

PostgreSQL 18.4; datos sintéticos del simulador.

| Resultado | Cantidad |
| --- | ---: |
| simulations | 1 |
| sensors | 12 |
| readings | 432 |
| events | 126 |
| predictions | 432 |
| reports | 4 |
| sensor_count | 12 |
| turn_count | 36 |
| positive_predictions | 46 |
| predictions_while_paused | 0 |

La importación repetida devolvió inserted=False. Se guardaron cuatro
informes: EDA, baseline, comparación e integración. Las lecturas
recuperadas de PostgreSQL conservan el contrato y vuelven a alimentar
la inferencia a través del gateway. Los 46 positivos de la demostración
son predicciones, no una nueva métrica de evaluación.

Los JSON completos están en reports/persona2_p2_7/ (ignorados por Git);
este resumen conserva la evidencia principal junto al código.
No hay despliegue, publicación, cambio de motores ni dependencia
del modelo respecto a Pygame. Se conserva el trabajo previo de Chagoya.

## Verificación final

Se ejecutaron los 25 scripts de DisasterCommandCenter desde una copia
temporal: 130 pruebas unitarias de Persona 2 y los 16 scripts originales
aprobados, sin omisiones. PostgreSQL 18.4 se ejecutó realmente y Pygame
arrancó en SDL dummy. También pasaron las 20 pruebas anteriores de Chagoya
con el pytest existente del Python base, sin añadir ese framework al proyecto.

Se compararon hashes de los archivos previamente existentes antes y
después: no cambiaron. Las modificaciones previas de Chagoya se conservan.
Los clústeres temporales se cerraron; no se instaló ningún servicio.

Los resultados por script están en reports/persona2_final/verificacion.json
y su versión legible en verificacion.md. La prueba de Chagoya tiene un
informe separado en la misma carpeta. Los artefactos siguen ignorados por
Git, según la regla original.

Para repetir las 130 pruebas de Persona 2, instala sus dependencias
opcionales y configura PostgreSQL de pruebas como se indicó arriba:

~~~powershell
.\.venv\Scripts\python.exe -B -m unittest discover -s DisasterCommandCenter -p "test_persona2_*.py" -v
~~~

La demostración sin base de datos requiere únicamente las dependencias de IA:

~~~powershell
.\.venv\Scripts\python.exe -B DisasterCommandCenter/demo_persona2_integracion.py
~~~
