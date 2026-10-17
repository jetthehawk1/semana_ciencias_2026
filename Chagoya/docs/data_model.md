# Disaster Command Center — Data Model

## 1. Objetivo

Este documento define los datos principales que serán utilizados por los diferentes módulos de **Disaster Command Center**.

El objetivo es establecer un formato común para que los módulos de simulación, sensores, inteligencia artificial, base de datos y rutas puedan intercambiar información sin depender directamente entre sí.

---

# 2. ZoneState

Representa el estado actual de una zona del campus.

Una zona puede ser un salón, laboratorio, pasillo, escalera, patio, salida u otro espacio definido en el mapa.

## Campos

| Campo | Tipo | Descripción | Ejemplo |
|---|---|---|---|
| `zone_id` | string | Identificador único de la zona | `"LAB_A1"` |
| `zone_type` | string | Tipo de zona | `"LAB"` |
| `temperature` | float | Temperatura actual en °C | `42.5` |
| `smoke` | float | Concentración normalizada de humo | `0.63` |
| `co` | float | Concentración de monóxido de carbono en ppm | `85.0` |
| `fire_intensity` | float | Intensidad del incendio entre 0.0 y 1.0 | `0.20` |
| `occupancy` | integer | Número aproximado de personas presentes | `14` |
| `hazardous_materials` | boolean | Indica si hay materiales peligrosos | `true` |
| `risk_level` | string | Nivel de riesgo actual | `"DANGER"` |

## Ejemplo

```json
{
  "zone_id": "LAB_A1",
  "zone_type": "LAB",
  "temperature": 42.5,
  "smoke": 0.63,
  "co": 85.0,
  "fire_intensity": 0.20,
  "occupancy": 14,
  "hazardous_materials": true,
  "risk_level": "DANGER"
}
```

---

# 3. Tipos de zona

Los valores permitidos inicialmente para `zone_type` serán:

| Valor | Descripción |
|---|---|
| `WALL` | Pared |
| `HALLWAY` | Pasillo |
| `CLASSROOM` | Salón |
| `LAB` | Laboratorio |
| `STAIR` | Escalera |
| `PATIO` | Patio |
| `DOOR` | Puerta |
| `EXIT` | Salida |
| `OUTSIDE` | Zona exterior |
| `BLOCKED` | Zona bloqueada |

Estos valores podrán ampliarse posteriormente si el mapa del campus lo requiere.

---

# 4. RiskLevel

Representa el nivel de riesgo de una zona.

Los valores permitidos son:

| Valor | Descripción |
|---|---|
| `SAFE` | Zona segura |
| `CAUTION` | Zona con condiciones que requieren precaución |
| `DANGER` | Zona peligrosa |
| `CRITICAL` | Zona crítica que debe evitarse |

En las primeras versiones, este valor podrá calcularse mediante reglas.

Posteriormente será generado por el módulo **Disaster AI**.

---

# 5. Sensor

Representa un sensor virtual instalado dentro del campus.

## Campos

| Campo | Tipo | Descripción | Ejemplo |
|---|---|---|---|
| `sensor_id` | string | Identificador único del sensor | `"SENSOR_TEMP_01"` |
| `zone_id` | string | Zona donde está ubicado | `"LAB_A1"` |
| `sensor_type` | string | Tipo de sensor | `"MULTI"` |
| `position_x` | integer | Posición X dentro del mapa | `15` |
| `position_y` | integer | Posición Y dentro del mapa | `8` |
| `status` | string | Estado operativo del sensor | `"ACTIVE"` |

## Ejemplo

```json
{
  "sensor_id": "SENSOR_01",
  "zone_id": "LAB_A1",
  "sensor_type": "MULTI",
  "position_x": 15,
  "position_y": 8,
  "status": "ACTIVE"
}
```

---

# 6. SensorReading

Representa una lectura generada por un sensor en un instante determinado.

## Campos

| Campo | Tipo | Descripción | Ejemplo |
|---|---|---|---|
| `sensor_id` | string | Sensor que generó la lectura | `"SENSOR_01"` |
| `zone_id` | string | Zona asociada | `"LAB_A1"` |
| `timestamp` | datetime | Fecha y hora de la lectura | `"2026-10-13T10:30:15"` |
| `temperature` | float | Temperatura en °C | `42.5` |
| `smoke` | float | Concentración de humo entre 0.0 y 1.0 | `0.63` |
| `co` | float | Monóxido de carbono en ppm | `85.0` |
| `fire_detected` | boolean | Indica si existe presencia de fuego | `true` |
| `fire_intensity` | float | Intensidad estimada del fuego | `0.20` |
| `occupancy` | integer | Número aproximado de personas | `14` |

## Ejemplo

```json
{
  "sensor_id": "SENSOR_01",
  "zone_id": "LAB_A1",
  "timestamp": "2026-10-13T10:30:15",
  "temperature": 42.5,
  "smoke": 0.63,
  "co": 85.0,
  "fire_detected": true,
  "fire_intensity": 0.20,
  "occupancy": 14
}
```

---

# 7. SensorStatus

Estados iniciales permitidos para un sensor:

| Valor | Descripción |
|---|---|
| `ACTIVE` | Sensor funcionando correctamente |
| `INACTIVE` | Sensor desactivado |
| `ERROR` | Sensor con algún fallo |

En versiones futuras podrán simularse:

- Lecturas faltantes.
- Ruido.
- Valores incorrectos.
- Sensores defectuosos.

---

# 8. WindState

Representa las condiciones actuales del viento.

## Campos

| Campo | Tipo | Descripción | Ejemplo |
|---|---|---|---|
| `speed` | float | Velocidad del viento en m/s | `4.5` |
| `direction` | float | Dirección en grados entre 0 y 359 | `90.0` |

## Ejemplo

```json
{
  "speed": 4.5,
  "direction": 90.0
}
```

Inicialmente se utilizará la siguiente convención:

- `0°` = Norte
- `90°` = Este
- `180°` = Sur
- `270°` = Oeste

---

# 9. RiskInput

Representa la información que recibirá el sistema de evaluación de riesgo.

En una primera versión será utilizada por reglas.

Posteriormente podrá utilizarse como entrada para **Disaster AI**.

## Campos iniciales

```text
temperature
smoke
co
fire_intensity
distance_to_fire
wind_speed
wind_direction
zone_type
hazardous_materials
nearby_risk
occupancy
```

## Ejemplo

```json
{
  "temperature": 42.5,
  "smoke": 0.63,
  "co": 85.0,
  "fire_intensity": 0.20,
  "distance_to_fire": 12.0,
  "wind_speed": 4.5,
  "wind_direction": 90.0,
  "zone_type": "LAB",
  "hazardous_materials": true,
  "nearby_risk": "DANGER",
  "occupancy": 14
}
```

---

# 10. RiskPrediction

Representa el resultado producido por el módulo encargado de evaluar el riesgo.

## Campos

| Campo | Tipo | Descripción |
|---|---|---|
| `zone_id` | string | Zona evaluada |
| `risk_level` | string | Nivel de riesgo calculado |
| `timestamp` | datetime | Momento del cálculo |
| `source` | string | Sistema que realizó la clasificación |

## Ejemplo

```json
{
  "zone_id": "LAB_A1",
  "risk_level": "DANGER",
  "timestamp": "2026-10-13T10:30:15",
  "source": "RULE_ENGINE"
}
```

Posteriormente `source` podrá utilizar valores como:

```text
RULE_ENGINE
DISASTER_AI
```

---

# 11. Unidades y rangos iniciales

| Variable | Unidad / rango |
|---|---|
| Temperatura | °C |
| Humo | 0.0 - 1.0 |
| CO | ppm |
| Intensidad del fuego | 0.0 - 1.0 |
| Ocupación | Número de personas |
| Velocidad del viento | m/s |
| Dirección del viento | 0° - 359° |
| Distancia | Metros o unidades equivalentes del mapa |

Los rangos de humo e intensidad de fuego son representaciones simplificadas de la simulación y podrán ajustarse posteriormente.

---

# 12. Flujo de datos

El flujo inicial esperado será:

```text
SIMULACIÓN
    ↓
Estado de las zonas
    ↓
SENSORES VIRTUALES
    ↓
SensorReading
    ↓
PROCESAMIENTO
    ↓
RiskInput
    ↓
MOTOR DE RIESGO / DISASTER AI
    ↓
RiskPrediction
    ↓
EVACUATION OPTIMIZER
```

La simulación será responsable de generar el estado físico.

Persona 2 será responsable de transformar estos datos en lecturas y niveles de riesgo.

El módulo de evacuación utilizará los niveles de riesgo para decidir qué caminos deben evitarse.

---

# 13. Responsabilidad de cada módulo

## Simulation

Produce principalmente:

```text
temperature
smoke
fire_intensity
occupancy
wind
zone state
```

## Sensors

Convierte el estado de la simulación en:

```text
SensorReading
```

## Processing

Valida y transforma las lecturas en:

```text
RiskInput
```

## Disaster AI

Recibe:

```text
RiskInput
```

Y produce:

```text
RiskPrediction
```

## Routing

Consume principalmente:

```text
risk_level
smoke
fire_intensity
congestion
```

para calcular o recalcular rutas.

---

# 14. Decisiones pendientes

Los siguientes puntos todavía deberán definirse durante el desarrollo:

- Valores exactos que separan `SAFE`, `CAUTION`, `DANGER` y `CRITICAL`.
- Frecuencia con la que los sensores generan lecturas.
- Frecuencia con la que se almacena información en PostgreSQL.
- Rangos definitivos de humo.
- Fórmula de generación de CO.
- Modelo definitivo de Disaster AI.
- Forma exacta de calcular `distance_to_fire`.
- Unidades utilizadas para distancias dentro del mapa.

Estas decisiones no deben fijarse de manera arbitraria hasta realizar pruebas con la simulación.

---

# 15. Primera versión

Para la primera integración del sistema solamente será obligatorio implementar:

```text
ZoneState
Sensor
SensorReading
RiskLevel
```

`RiskInput`, `RiskPrediction` y la integración con Machine Learning podrán añadirse cuando la simulación de sensores esté funcionando correctamente.

El objetivo inicial es poder realizar el siguiente flujo:

```text
ZoneState
    ↓
Sensor
    ↓
SensorReading
    ↓
RiskLevel
```

Esta será la primera interfaz funcional entre la simulación y el trabajo de Datos e IA.