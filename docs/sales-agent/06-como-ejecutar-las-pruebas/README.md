[Volver a la guía del agente](../README.md)

# Ejecutar y actualizar el laboratorio

## Repetición puntual tras desplegar Repair 5

El modelo se lee de la configuración publicada, no de un nombre escrito en el guion. En la última evidencia era `openai/gpt-4o-mini` versión de configuración 8; comprobar el modelo y digest exportados si cambian los settings. Lead simulado: guionado, sin modelo. Juez LLM: ninguno.

```bash
docker exec -i -w /app bp_api_prod python -m tools.sales_ai.synthetic_lab \
  --suite compact-battery \
  --configuration-id cbc8abfa-23d3-417c-97dd-fd12e3406ed4 \
  --cases first_time_A move_up_B unknown_A \
  --max-calls 60 --max-turns 8 \
  --output /tmp/sales-compact-repair-5
```

Se esperan dos visitas. Copiar el ZIP incluso si termina en `FAIL`:

```bash
docker cp bp_api_prod:/tmp/sales-compact-repair-5/synthetic-sales-results.zip ~/sales-compact-repair-5.zip
```

En PowerShell:

```powershell
& "$env:WINDIR\System32\OpenSSH\scp.exe" jorge@206.189.118.99:~/sales-compact-repair-5.zip "$env:USERPROFILE\Downloads\sales-compact-repair-5.zip"
```

El worker usa SQLite privado, credenciales de configuración solo para inferencia y guardas de red/DB. No ejecutar seeds contra PostgreSQL productivo. No escribe leads, citas u outbox productivos ni llama Calendar externo. Usa primer vendedor elegible en la simulación, no el cursor round-robin productivo. Los enlaces locales no validan autenticación HTTP pública.

## Regenerar el snapshot de datos

Desde la raíz, con las dependencias y variables de test habituales del backend:

```bash
PYTHONPATH=backend python -m tools.sales_ai.export_documentation --output docs/sales-agent --clock 2026-11-11T06:34:00
```

[Exportador de fixtures](../../../backend/tools/sales_ai/export_documentation.py). Crea SQLite en memoria, archivos temporales y exporta campos permitidos; no consulta la base de producción ni llama un modelo. Los horarios son un snapshot fijo para lectura, no disponibilidad vigente.

## Incorporar resultados y regenerar figuras

Mantener los ZIP originales fuera de Git. El importador acepta únicamente nombres de suites sintéticas conocidas, exige `synthetic_only` y rechaza escrituras/contactos productivos. Publica campos seleccionados, no prompts completos ni credenciales.

```bash
python docs/sales-agent/06-como-ejecutar-las-pruebas/herramientas/importar_resultados.py --source /ruta/a/zips --output docs/sales-agent
python docs/sales-agent/06-como-ejecutar-las-pruebas/herramientas/generar_graficas.py
```

[Importador](herramientas/importar_resultados.py) · [Generador NumPy/Matplotlib](herramientas/generar_graficas.py) · [Anotaciones humanas](../04-conversaciones/revisiones-humanas.json)

Para generar figuras se necesitan `numpy` y `matplotlib` en el entorno documental; no se añadieron dependencias al runtime del agente. Añadir anotaciones con clave `nombre-del-zip-sin-extension:caso`; el importador las conserva. Antes de publicar nuevos archivos, revisar que todos los datos sean ficticios y que la etiqueta humana no se confunda con una evaluación automática. Esta exportación no es un importador de datos reales de clientes. El importador actualiza JSON, CSV y resúmenes por corrida; al incorporar corridas nuevas también hay que actualizar el texto, las tablas e índices Markdown y su revisión humana. Los IDs de recursos pueden cambiar al regenerar fixtures; siempre usar las relaciones del mismo snapshot.

## Qué falta después de esta iteración

1. Repetir los tres casos con el mismo modelo/configuración para comprobar el alcance y el compositor.
2. Si pasan y la lectura humana es favorable, ampliar a los otros escenarios conservando denominadores.
3. Probar transporte real y calendario por separado, con su autorización y configuración correspondientes.
4. Diseñar evaluación de inactividad prolongada, notificación de nuevos slots y cancelación/reagendamiento antes de afirmar cobertura sobre ellos.
