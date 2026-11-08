# Grupo A — Corrección del preflight de despliegue

Fecha: 8 de noviembre de 2026. Base: `0a323e0d1130fb913defe30afe33d5c0b047a220`.

## Causa

El grupo A se comprobó inicialmente en un checkout, donde `backend/tools` está
disponible. El Dockerfile de producción solo copiaba `app`, Alembic y migraciones.
Actions monta `backend/tests` en `/app/tests`, pero el módulo que esas pruebas
importan, `tools.sales_ai`, no existía en la imagen. La colección falló con:

```text
ModuleNotFoundError: No module named 'tools'
```

El preflight del intento compartido se detuvo antes de `RELEASE_STARTED=true`,
del retiro de contenedores y de las migraciones. Ese fallo no llegó a sustituir
la release anterior.

También se corrigió una segunda incompatibilidad que habría aparecido después:
las referencias a pruebas del repositorio en T01–T26 calculaban la raíz a partir
de `/app/tests`, en vez de usar el montaje `/preflight` configurado por Actions.

## Cambios

1. `backend/Dockerfile` copia expresamente `backend/tools` en `/app/tools`.
   No copia `.env`, fixtures ni exportaciones privadas. Las herramientas siguen
   requiriendo invocación explícita y no alteran el arranque de API/worker.
2. `backend/tests/test_sales_ai_group_a.py` respeta `SALES_ACCEPTANCE_ROOT` y
   comprueba que sea una ruta absoluta existente, como la matriz anterior de
   27 issues. En un checkout conserva su resolución local cuando no hay override.

Se mantienen el preflight completo, las pruebas, permisos y validaciones del
despliegue. No se modifica el flujo comercial, la configuración IA ni el esquema.
Los grupos B–L continúan pendientes.

## Verificación

Se preparó una disposición física aislada a partir de las instrucciones `COPY`
del Dockerfile: directorio de aplicación con solo los archivos de la imagen,
copias de tests y árbol de referencias separados, con las rutas de los montajes
de Actions y los modos de archivo originales. Se bloquearon escrituras de directorio
y se verificó por hashes que el contenido de las fuentes no cambió durante la suite.
No se usó el checkout para resolver imports.

- Antes de la corrección: se reprodujo `ModuleNotFoundError: tools`, exit code 2.
- Después: 38 pruebas focalizadas aprobadas (37 de A y la matriz anterior).
- Backend completo en esa disposición: resultado registrado en
  `group-a-preflight-fix-report.json`.
- Checkout normal: 37 pruebas de A aprobadas.

El entorno local no dispone de Docker; esta comprobación reproduce las rutas,
copias, modos de archivo y variables de prueba, pero no constituye una nueva ejecución
de la imagen en DigitalOcean. La construcción y el despliegue reales se verificarán
en el siguiente run de Actions. No se enviaron mensajes ni se usaron proveedores reales.

## Aplicación

Aplicar el diferencial sobre el commit base indicado y subir un **commit nuevo**.
Reejecutar el job del commit anterior no incorpora estos cambios.
No se requiere ejecutar SQL ni cambiar secretos/variables de Actions.

La entrega incluye los archivos completos modificados y un patch con sus rutas
relativas. El reporte y el estado acumulado dejan constancia de esta corrección.
