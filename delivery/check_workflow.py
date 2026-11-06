from pathlib import Path
import subprocess
import yaml

root = Path('/workspace/scratch/f7e8c4a0ec42/bp-preflight-fix')
workflow = yaml.safe_load((root/'.github/workflows/deploy.yml').read_text())
scripts = [step['with']['script'] for job in workflow['jobs'].values()
           for step in job.get('steps', []) if isinstance(step.get('with'), dict) and 'script' in step['with']]
script = next(value for value in scripts if 'python -m pytest -q /app/tests' in value)
subprocess.run(['bash', '-n'], input=script, text=True, check=True)
for value in ['-e PYTHONPATH=/app', '-e SALES_ACCEPTANCE_ROOT=/preflight',
              '-v "$REPOSITORY_DIR/backend/tests:/app/tests:ro"',
              '-v "$REPOSITORY_DIR/docs:/preflight/docs:ro"',
              '-v "$REPOSITORY_DIR/backend/tests:/preflight/backend/tests:ro"']:
    assert value in script, value
assert script.index('python -m pytest -q /app/tests') < script.index('RELEASE_STARTED=true')
assert 'trap rollback ERR' in script
print('PASS: YAML parsing, Bash syntax, read-only references, image PYTHONPATH, preflight-before-release and rollback guard.')
