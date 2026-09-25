# Hotfix de GitHub Actions — Black Penguin

Este paquete elimina únicamente los dos archivos obsoletos que provocan:

- el segundo workflow `Deploy Firebase Admin Bridge`;
- las tres pruebas fallidas del antiguo transporte de correos de citas.

## Aplicación en Windows PowerShell

1. Extrae `_blackpenguin_ci_hotfix` dentro de la raíz de tu repositorio `BlackPenguin`.
2. Abre PowerShell en la raíz del repositorio.
3. Ejecuta:

```powershell
powershell -ExecutionPolicy Bypass -File .\_blackpenguin_ci_hotfix\apply_hotfix.ps1
```

## Aplicación en Linux, macOS o Git Bash

```bash
bash ./_blackpenguin_ci_hotfix/apply_hotfix.sh
```

## Verificación y commit

El resultado esperado de `git status --short` es:

```text
D  .github/workflows/deploy-firebase-admin-bridge.yml
D  backend/tests/test_firebase_admin_email_bridge.py
?? _blackpenguin_ci_hotfix/
```

No agregues `_blackpenguin_ci_hotfix` al commit. Crea el commit y sube los cambios:

```bash
git commit -m "fix(ci): remove retired Firebase email bridge workflow and tests"
git push origin main
```

Después del push puedes borrar localmente la carpeta `_blackpenguin_ci_hotfix`.

No vuelvas a ejecutar el workflow fallido del commit anterior: ese rerun conservaría los archivos obsoletos.
