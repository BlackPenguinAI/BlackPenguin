#!/usr/bin/env bash
set -euo pipefail

script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
repo_root="$(dirname -- "$script_dir")"
targets=(
  ".github/workflows/deploy-firebase-admin-bridge.yml"
  "backend/tests/test_firebase_admin_email_bridge.py"
)

if [[ ! -d "$repo_root/.git" ]]; then
  echo "Extrae la carpeta _blackpenguin_ci_hotfix dentro de la raiz del repositorio BlackPenguin." >&2
  exit 1
fi

for target in "${targets[@]}"; do
  if [[ -e "$repo_root/$target" ]]; then
    git -C "$repo_root" rm -- "$target"
  else
    echo "Ya estaba eliminado: $target"
  fi
done

echo
echo "Cambios preparados:"
git -C "$repo_root" diff --cached --name-status -- "${targets[@]}"
echo
echo "Hotfix aplicado. Revisa el resultado y luego crea el commit indicado en COMMIT_MESSAGE.txt."
