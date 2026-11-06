from pathlib import Path
import os,re,subprocess,yaml
root=Path('/workspace/scratch/f7e8c4a0ec42/bp-global-patch')
w=yaml.safe_load((root/'.github/workflows/deploy.yml').read_text())
step=w['jobs']['deploy']['steps'][0]
assert step['env']['SALES_DIALOGUE_RUNTIME_ENABLED']=="${{ vars.SALES_DIALOGUE_RUNTIME_ENABLED || 'false' }}"
assert 'SALES_DIALOGUE_RUNTIME_ENABLED' in step['with']['envs'].split(',')
script=step['with']['script']
subprocess.run(['bash','-n'],input=script,text=True,check=True)
validation=re.search(r'case "\$\{SALES_DIALOGUE_RUNTIME_ENABLED:-false\}" in.*?esac',script,re.S).group()
for value,expected in [(None,0),('true',0),('false',0),('TRUE',1),('yes',1),('true\nINJECTED=x',1)]:
    env={**os.environ};env.pop('SALES_DIALOGUE_RUNTIME_ENABLED',None)
    if value is not None:env['SALES_DIALOGUE_RUNTIME_ENABLED']=value
    result=subprocess.run(['bash','-c',validation],env=env,capture_output=True)
    assert result.returncode==expected,(value,result.returncode)
assert 'echo "SALES_DIALOGUE_RUNTIME_ENABLED=${SALES_DIALOGUE_RUNTIME_ENABLED:-false}"' in script
assert script.count('--env-file backend/.env')>=2
assert '-e SALES_ACCEPTANCE_ROOT=/preflight' in script
assert script.index('python -m pytest -q /app/tests')<script.index('RELEASE_STARTED=true')
print('PASS: YAML/Bash, repository variable forwarding, persistent flag generation, 6 flag validation cases, shared environment, preflight ordering.')
