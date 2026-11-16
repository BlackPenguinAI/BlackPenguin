# Dos repeticiones de la batería LangGraph

Esta entrega actualiza documentación, evidencia y comandos; conserva el mismo motor de `94f72bc`. No se modifica el modelo ni la configuración publicada. Las repeticiones pagadas se ejecutan en el servidor por el operador; todavía no se ejecutaron.

Aplicar el diferencial desde la raíz del repositorio y publicar:

```bash
git add .
git commit -m "Document LangGraph six-case success and stability evaluation"
git push
```

Después del despliegue, copiar y ejecutar el bloque completo siguiente en el servidor. No desplegar ni editar AI Settings mientras corre. Las dos evaluaciones son secuenciales; se conserva un FAIL y se ejecuta la segunda. Se copia cada ZIP con `docker cp` y se crea `~/sales-graph-stability.zip`, con ambos resultados originales y un resumen de costos y comparabilidad. El control de contenedor detecta cambios, pero no reemplaza la revisión del catálogo/fechas y de los mensajes reales del reporte.

**Consumo total estimado de las dos ejecuciones nuevas: USD 0.24–0.40**. Cada corrida tiene un límite de 300 llamadas; no es un límite de dinero. El laboratorio no contacta leads reales ni crea citas en la base productiva.

```bash
#!/usr/bin/env bash
# Ejecutar con bash. Conservar evidencia aunque una evaluación termine en FAIL.
set -u
run_sales_stability() {
  local container_start diagnostic_run diagnostic_exit run_number
  container_start=$(docker inspect --format '{{.Id}} {{.Image}} {{index .Config.Labels "org.opencontainers.image.revision"}}' bp_api_prod) || return 1
  docker inspect --format '{{.Name}} revision={{index .Config.Labels "org.opencontainers.image.revision"}}' bp_api_prod bp_worker_prod || return 1
  docker exec -i -w /app bp_api_prod python -c 'from app.modules.sales_agent.interpretation_input import SYSTEM_VERSION; print(SYSTEM_VERSION); assert SYSTEM_VERSION == "sales-interpretation-system/2.8"' || return 1
  local report_dir="$HOME/sales-graph-stability-$(date -u +%Y%m%dT%H%M%SZ)-$$"
  mkdir -p "$report_dir" || return 1
  printf '%s\n' "$container_start" > "$report_dir/container-start.txt"
  for run_number in 1 2; do
    if [[ "$(docker inspect --format '{{.Id}} {{.Image}} {{index .Config.Labels "org.opencontainers.image.revision"}}' bp_api_prod)" != "$container_start" ]]; then
      echo "El contenedor cambió. Detener y conservar la evidencia en $report_dir."
      return 1
    fi
    diagnostic_run="sales-graph-stability-$run_number-$(date -u +%Y%m%dT%H%M%SZ)-$$"
    docker exec -i -w /app bp_api_prod python -m tools.sales_ai.synthetic_lab \
      --suite observation-battery --orchestrator graph-observe \
      --max-calls 300 --max-turns 10 --output "/tmp/$diagnostic_run"
    diagnostic_exit=$?
    printf '%s\n' "$diagnostic_exit" > "$report_dir/run-$run_number-exit.txt"
    docker cp \
      "bp_api_prod:/tmp/$diagnostic_run/synthetic-sales-results.zip" \
      "$report_dir/sales-graph-stability-$run_number.zip" || echo "No se pudo copiar la corrida $run_number."
    printf 'Corrida %s: código %s\n' "$run_number" "$diagnostic_exit"
  done
  docker inspect --format '{{.Id}} {{.Image}} {{index .Config.Labels "org.opencontainers.image.revision"}}' bp_api_prod > "$report_dir/container-end.txt"
  python3 - "$report_dir" "$HOME/sales-graph-stability.zip" <<'PY'
import json,sys,zipfile
from pathlib import Path
source,destination=map(Path,sys.argv[1:]);rows=[];issues=[]
for n in (1,2):
    path=source/f'sales-graph-stability-{n}.zip'
    if not path.exists():
        issues.append(f'Falta evidencia de corrida {n}');continue
    with zipfile.ZipFile(path) as z:r=json.loads(z.read('summary.json'))
    usage=r.get('provider_usage',{});cases=r.get('cases',[])
    rows.append(dict(run=n,commit=r.get('commit'),model=r.get('sales_model'),configuration_sha256=r.get('configuration_sha256'),suite_version=r.get('version'),mode=r.get('coordinator_mode'),status=r.get('status'),passed_cases=(r.get('split_results',{}).get('observation') or {}).get('passed'),cases=len(cases),bookings=sum(len(c.get('meetings',[])) for c in cases),turns=sum(len(c.get('turns',[])) for c in cases),provider_calls=r.get('provider_calls'),cost_usd=usage.get('cost_usd'),cost_complete=r.get('cost_reporting_complete')))
    if (r.get('sales_model'),r.get('configuration_sha256'),r.get('coordinator_mode'),r.get('version')) != ('openai/gpt-4o-mini','51ff65376dad421328dab993a4fc71939489386f1ed173514cf13a244ac79f1c','graph-observe','sales-observation-battery/1.2'):
        issues.append(f'Corrida {n}: modelo/configuración/modo/batería difiere de la base')
    if len(cases)!=6 or any(t.get('metadata',{}).get('engine')!='sales-langgraph/2.0' for c in cases for t in c.get('turns',[])):
        issues.append(f'Corrida {n}: casos o motor inesperados')
    if int((source/f'run-{n}-exit.txt').read_text())!=0:issues.append(f'Corrida {n}: evaluación terminó con código no cero')
if len({row['commit'] for row in rows})>1:issues.append('Las corridas no usaron el mismo commit')
if (source/'container-start.txt').read_text()!=(source/'container-end.txt').read_text():issues.append('Cambió el contenedor durante las corridas')
report=dict(rows=rows,issues=issues,total_new_cost_usd_recorded=sum(row['cost_usd'] or 0 for row in rows),all_costs_reported=len(rows)==2 and all(row['cost_complete'] for row in rows),all_six_checks_pass_twice=len(rows)==2 and not issues and all(row['status']=='PASS' and row['passed_cases']==6 for row in rows),overall_dialogue_quality='NOT_EVALUATED',note='Dos corridas nuevas; no suman nuevamente el costo de la base. Revisar trazas y contenido antes de afirmar calidad integral.')
(source/'resumen-estabilidad.json').write_text(json.dumps(report,indent=2,ensure_ascii=False)+'\n')
with zipfile.ZipFile(destination,'w',zipfile.ZIP_DEFLATED) as z:
    for path in sorted(source.iterdir()):
        if path.is_file():z.write(path,path.name)
print(json.dumps(report,indent=2,ensure_ascii=False));print('Archivo generado:',destination)
PY
}
run_sales_stability
```

Descargar desde PowerShell:

```powershell
& "$env:WINDIR\System32\OpenSSH\scp.exe" jorge@206.189.118.99:~/sales-graph-stability.zip "$env:USERPROFILE\Downloads\sales-graph-stability.zip"
```

También se puede ejecutar el archivo `ejecutar-estabilidad-langgraph.sh` con Bash si el repositorio está disponible en el servidor. Se requiere Python 3 en el host para agrupar los archivos; no requiere instalar paquetes. Si el contenedor cambia entre evaluaciones, se detiene antes de iniciar otra corrida y deja la evidencia parcial en la carpeta mostrada.
