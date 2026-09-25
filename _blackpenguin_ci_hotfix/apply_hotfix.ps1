$ErrorActionPreference = "Stop"

$repoRoot = Split-Path -Parent $PSScriptRoot
$targets = @(
    ".github/workflows/deploy-firebase-admin-bridge.yml",
    "backend/tests/test_firebase_admin_email_bridge.py"
)

if (-not (Test-Path -LiteralPath (Join-Path $repoRoot ".git"))) {
    throw "Extrae la carpeta _blackpenguin_ci_hotfix dentro de la raiz del repositorio BlackPenguin."
}

Push-Location $repoRoot
try {
    foreach ($target in $targets) {
        $fullPath = Join-Path $repoRoot $target
        if (Test-Path -LiteralPath $fullPath) {
            git rm -- $target
            if ($LASTEXITCODE -ne 0) {
                throw "No se pudo eliminar del repositorio: $target"
            }
        }
        else {
            Write-Host "Ya estaba eliminado: $target"
        }
    }

    Write-Host ""
    Write-Host "Cambios preparados:"
    git diff --cached --name-status -- $targets
    if ($LASTEXITCODE -ne 0) {
        throw "No se pudo verificar el diff preparado."
    }

    Write-Host ""
    Write-Host "Hotfix aplicado. Revisa el resultado y luego crea el commit indicado en COMMIT_MESSAGE.txt."
}
finally {
    Pop-Location
}
