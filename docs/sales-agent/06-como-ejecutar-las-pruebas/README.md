[Volver a la guía del agente](../README.md)

# Ejecutar y actualizar el laboratorio

## Ejecutar los 16 casos de la batería compacta 2

El modelo se lee de la configuración publicada, no de un nombre escrito en el guion. En la última evidencia era `openai/gpt-4o-mini` versión de configuración 8; comprobar el modelo y digest exportados si cambian los settings. Lead simulado: guionado, sin modelo. Juez LLM: ninguno.

```bash
docker exec -i -w /app bp_api_prod python -m tools.sales_ai.synthetic_lab \
  --suite compact-battery \
  --configuration-id cbc8abfa-23d3-417c-97dd-fd12e3406ed4 \
  --max-calls 320 --max-turns 8 \
  --output /tmp/sales-compact-battery-2
```

Repair 7 aprobó el subconjunto de tres. Ahora se esperan ocho visitas entre 16 escenarios; el resto puede cerrar correctamente sin cita. La ampliación no está ejecutada todavía. Copiar el ZIP incluso si termina en `FAIL`:

```bash
docker cp bp_api_prod:/tmp/sales-compact-battery-2/synthetic-sales-results.zip ~/sales-compact-battery-2.zip
```

En PowerShell:

```powershell
& "$env:WINDIR\System32\OpenSSH\scp.exe" jorge@206.189.118.99:~/sales-compact-battery-2.zip "$env:USERPROFILE\Downloads\sales-compact-battery-2.zip"
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

## Trabajo siguiente

1. Ejecutar una vez la batería compacta 2 y conservar el ZIP aunque reporte FAIL.
2. Revisar los 16 desenlaces, llamadas, reparaciones y consumo completo/parcial; corregir y repetir solo los casos afectados.
3. Ampliar luego variantes y longitud; transporte, Calendar, inactividad y cancelación/reagendamiento se evalúan por separado.

La explicación y los presupuestos completos están en la [guía principal](../README.md). El consumo estimado total de la batería es USD 0.32–0.43, reserva USD 0.64–0.86; el límite de llamadas no impone un techo monetario. Esta preparación no cambió el motor ni llamó a un modelo pagado.
