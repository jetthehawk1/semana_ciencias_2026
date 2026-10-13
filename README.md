# Disaster Command Center

Sistema inteligente de detección, simulación y evacuación dinámica ante incendios en UABC Unidad Punta Morro.

## Descripción

Disaster Command Center es un proyecto desarrollado para la Semana de Ciencias UABC 2026.

El objetivo es crear una simulación interactiva de una emergencia por incendio dentro de UABC Unidad Punta Morro, utilizando un mapa digital del campus, sensores virtuales, análisis de riesgo y algoritmos de evacuación dinámica.

A diferencia de una evacuación tradicional con rutas fijas, el sistema podrá modificar las rutas en tiempo real dependiendo de las condiciones de la emergencia.

Entre los factores considerados se encuentran:

*Temperatura
*Concentración de humo
*Monóxido de carbono
*Intensidad y propagación del incendio
*Velocidad y dirección del viento
*Congestión de pasillos y salidas
*Estado de accesos
*Ocupación de las zonas
*Presencia de laboratorios o materiales peligrosos

Objetivo

Demostrar cómo un sistema basado en datos puede responder dinámicamente ante una emergencia que cambia constantemente.

Por ejemplo, si el humo comienza a despalzarse hacia una salida utilizada actualmente, el sistema deberá:

1.- Detectar el aumento del riesgo mediante sensores virtuales.
2.- Actualizar el nivel de peligro de la zona.
3.- Identificar que la ruta actual ya no es segura.
4.- Calcular una nueva ruta de evacuación.
5.- Redirigir a las personas simuladas.
6.- Mostrar una alerta de ruta recalculada.

## Componentes principales

El proyecto estará dividido en módulos independientes.

### Simulación

Responsable de representar:
*Mapa del campus
*Personas
*Fuego
*Humo
*Viento
*Zonas y celdas
*Sensores virtuales

### Disaster AI

Módulo encargado de analizar los datos obtenidos por los sensores y clasificar el nivel de riesgo de las diferentes zonas.

