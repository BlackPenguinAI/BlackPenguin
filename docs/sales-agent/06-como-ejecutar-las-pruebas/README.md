[Volver a la guía del agente](../README.md)

# Ejecutar y actualizar el laboratorio

## Repetir solo los tres casos tras desplegar Repair 8

La batería compacta 2 ya se ejecutó: 13/16 aprobados y 7/8 visitas. Ahora se repiten `move_up_A`, `downsizing_B` y `portfolio_A`, con el mismo modelo/configuración. No hay otro LLM para el lead ni juez.

```bash
docker exec -i -w /app bp_api_prod python -m tools.sales_ai.synthetic_lab \
  --suite compact-battery \
  --configuration-id cbc8abfa-23d3-417c-97dd-fd12e3406ed4 \
  --cases move_up_A downsizing_B portfolio_A \
  --max-calls 80 --max-turns 8 --output /tmp/sales-compact-repair-8
```

Copiar el reporte incluso si falla; se esperan dos visitas, no tres:

```bash
docker cp bp_api_prod:/tmp/sales-compact-repair-8/synthetic-sales-results.zip ~/sales-compact-repair-8.zip
```

```powershell
& "$env:WINDIR\System32\OpenSSH\scp.exe" jorge@206.189.118.99:~/sales-compact-repair-8.zip "$env:USERPROFILE\Downloads\sales-compact-repair-8.zip"
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

## Conversaciones legibles y siguiente iteración

Después de importar los ZIP originales, ejecutar:

```bash
python docs/sales-agent/06-como-ejecutar-las-pruebas/herramientas/generar_conversaciones_legibles.py
```

Genera una ficha Markdown por conversación registrada; no llama un modelo ni inventa interpretaciones. Los mensajes, campos y controles vienen del JSON y cada ficha enlaza al original. La guía principal conserva toda la explicación del experimento.

Repair 8 todavía debe evaluarse con el modelo publicado. Corregir primero los casos que fallen antes de repetir los 16. El consumo estimado total del subconjunto es USD 0.04–0.09, reserva USD 0.08–0.18; no se suma al histórico ni es un techo garantizado.
