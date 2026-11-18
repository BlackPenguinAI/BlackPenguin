# P2-B: auditoría de reparaciones y ablación offline

**Base:** `f1fb3e983658684ea670b624f8278e83dd7acd57` (P1-C.1 con CI corregido).

## Alcance y regla de decisión

P2-B **no elimina aún reparaciones del flujo de producción**. Antes de quitar una
normalización necesitamos evidencia de que no modifica ninguno de los contratos
interpretados, no oculta solicitudes independientes y no afecta evidencia,
restricciones, consentimiento, reservas, registro de mensajes ni controles de
seguridad. Una frecuencia observada de cero **no es prueba de redundancia**.

El auditor analiza solamente ZIPs sintéticos que contienen `report.json`; no
consulta proveedores, base de datos ni llamadas reales. Los dos comandos de
P2-B generan únicamente estadísticas agregadas. Nunca publican el texto del
lead, prompts, respuestas crudas, identificadores de oportunidad ni evidencia
literal. El experimento de ablación reemplaza **en memoria, solo dentro de su
proceso de prueba**, cada normalizador; no aplica parches al código productivo.

## 1. Pruebas sin costo

```bash
# En el servidor, con los contenedores del commit P2-B ya desplegados
mkdir -p ~/bp-p2b-results

docker exec -i -w /app bp_api_prod \
  python -m tools.sales_ai.p2b_repair_selftest \
  2>&1 | tee ~/bp-p2b-results/selftest.log
```

Se esperan **7 tests OK**. Los selftests revisan minimización de datos, acción
desconocida, protección contra respuestas truncadas, rechazo de ZIPs no
sintéticos y la ausencia de desactivaciones autorizadas automáticamente.

## 2. Reutilizar la evidencia P1-C.1 sin gastar OpenRouter

El ZIP final del lote anterior se dejó en `~/bp-p1c1-results/closing-point.zip`
(en el host). Copiarlo al contenedor es una operación local:

```bash
test -f ~/bp-p1c1-results/closing-point.zip || exit 1

docker cp ~/bp-p1c1-results/closing-point.zip \
  bp_api_prod:/tmp/bp-p2b-reference.zip

docker exec -i -w /app bp_api_prod \
  python -m tools.sales_ai.p2b_repair_audit \
  --bundles /tmp/bp-p2b-reference.zip \
  --output /tmp/bp-p2b-audit.json \
  2>&1 | tee ~/bp-p2b-results/audit.log

docker exec -i -w /app bp_api_prod \
  python -m tools.sales_ai.p2b_repair_ablation \
  --bundles /tmp/bp-p2b-reference.zip \
  --approved-name 'Bay Residence' \
  --output /tmp/bp-p2b-ablation.json \
  2>&1 | tee ~/bp-p2b-results/ablation.log
```

`--approved-name` acepta varias repeticiones con etiquetas *verificadas del
catálogo sintético*. No agregar nombres que no existan ni usar nombres de leads
reales. La ausencia de nombres reduce la fidelidad del contexto comparado, por
lo que ninguna ablación concluye que un módulo puede retirarse automáticamente.

## 3. Recolectar resultados

```bash
docker cp bp_api_prod:/tmp/bp-p2b-audit.json \
  ~/bp-p2b-results/audit.json

docker cp bp_api_prod:/tmp/bp-p2b-ablation.json \
  ~/bp-p2b-results/ablation.json

tar -czf ~/bp-p2b-results.tar.gz -C ~ bp-p2b-results
ls -lh ~/bp-p2b-results.tar.gz
```

En PowerShell de Windows:

```powershell
& "$env:WINDIR\System32\OpenSSH\scp.exe" jorge@206.189.118.99:~/bp-p2b-results.tar.gz "$env:USERPROFILE\Downloads\bp-p2b-results.tar.gz"
```

Compartir solo este TAR agregado para que podamos decidir la siguiente fase.
**No adjuntar a terceros los ZIPs internos de conversaciones**: aunque son
sintéticos, contienen respuestas originales del modelo.

## 4. Criterios para retirar una reparación en P2-B.2

1. La ablación registra `replayed_comparisons > 0`, cero diferencias y cero
   errores frente al contrato original en un conjunto relevante de casos.
2. Añadir casos positivos y negativos que *activen* la reparación y demuestren
   que el normalizador no es necesario en el contrato v3. Los escenarios sin
   activación no cuentan como prueba de redundancia.
3. Confirmar equivalencia al pasar `Understanding`, validador semántico,
   planificador, observador, consentimiento y registros.
4. Cambiar una reparación a la vez; ejecutar CI y la batería `closing-point`
   reforzada, con 4/4 lecturas de financiamiento y 1/1 búsqueda de visita.
5. Usar rollback inmediato ante cualquier regresión, incluida una sola
   lectura omitida o fallo de observación que los checks generales no vean.

**No desactivar:** parsing estricto/evidencia actual, enlaces backend-owned,
restricciones, permisos de lectura/escritura, controles de opt-out, historial de
consentimiento, integridad de reservas y trazabilidad de operaciones.
