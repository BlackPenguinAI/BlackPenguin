"""Run real PostgreSQL races against an isolated, outbound-disabled Docker network.

No production .env, database, volume or container is reused. Requires the exact
candidate API image (including pytest); only test sources are mounted read-only.
"""
import argparse,json,re,secrets,subprocess,tempfile,time,uuid
from pathlib import Path
from xml.etree import ElementTree as ET

TESTS=['test_sales_booking_postgres.py','test_sales_dialogue_postgres.py','test_sales_runtime_postgres.py','test_sales_concurrency_postgres.py','test_sales_route_postgres.py']


def run(image,expected_commit,tests,output):
    if not re.fullmatch('[0-9a-f]{40}',expected_commit):raise ValueError('Provide the full candidate commit SHA.')
    tests=tests.resolve()
    if not all((tests/name).is_file() for name in TESTS):raise ValueError('The candidate test directory is incomplete.')
    revision=subprocess.check_output(['docker','image','inspect','--format','{{index .Config.Labels "org.opencontainers.image.revision"}}',image],text=True).strip()
    if revision!=expected_commit:raise ValueError('The API image revision does not match the candidate commit.')
    identifier='bp-sales-test-'+uuid.uuid4().hex[:12];network=identifier+'-net';container=identifier+'-pg'
    created_network=False;started_container=False
    result={'version':'sales-postgres-checks/1.0','candidate_commit':expected_commit,'mode':'isolated-real-postgresql',
            'status':'NOT_RUN','production_database_used':False,'provider_calls':0}
    output.parent.mkdir(parents=True,exist_ok=True)
    try:
        with tempfile.TemporaryDirectory(prefix='bp-sales-postgres-') as directory:
            directory=Path(directory);env=directory/'test.env';password=secrets.token_hex(24)
            values={'POSTGRES_DB':'bp_sales_test','POSTGRES_USER':'bp_sales_test','POSTGRES_PASSWORD':password,
                'SECRET_KEY':secrets.token_hex(32),'ACCESS_TOKEN_EXPIRE_MINUTES':'60','DATABASE_URL':'sqlite://',
                'ENVIRONMENT':'test','FIRST_SUPERADMIN_EMAIL':'test@example.invalid','FIRST_SUPERADMIN_PASSWORD':'test-only',
                'META_ACCESS_TOKEN':'test-only','OPENROUTER_API_KEY':'test-only','PYTHONPATH':'/app',
                'DIALOGUE_POSTGRES_TEST_URL':f'postgresql+psycopg2://bp_sales_test:{password}@postgres:5432/bp_sales_test'}
            env.write_text('\n'.join(k+'='+v for k,v in values.items())+'\n');env.chmod(0o600)
            subprocess.run(['docker','network','create','--internal',network],check=True,stdout=subprocess.DEVNULL);created_network=True
            subprocess.run(['docker','run','-d','--rm','--name',container,'--network',network,'--network-alias','postgres','--env-file',str(env),'postgres:16'],check=True,stdout=subprocess.DEVNULL);started_container=True
            for _ in range(45):
                if subprocess.run(['docker','exec',container,'pg_isready','-U','bp_sales_test','-d','bp_sales_test'],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL).returncode==0:break
                time.sleep(1)
            else:raise RuntimeError('The disposable PostgreSQL server did not become ready.')
            log=output.with_suffix('.log');xml=directory/'junit.xml'
            with log.open('w') as stream:
                completed=subprocess.run(['docker','run','--rm','--network',network,'--env-file',str(env),
                    '-v',str(tests)+':/app/tests:ro','-v',str(directory)+':/evidence',image,
                    'python','-m','pytest','-q',*['/app/tests/'+name for name in TESTS],'--disable-warnings','--tb=short','--junitxml=/evidence/junit.xml'],stdout=stream,stderr=subprocess.STDOUT)
            cases=list(ET.parse(xml).iter('testcase')) if xml.exists() else []
            skipped=sum(c.find('skipped') is not None for c in cases);failed=sum(c.find('failure') is not None or c.find('error') is not None for c in cases)
            result.update(exit_code=completed.returncode,total=len(cases),failed=failed,skipped=skipped,
                status='PASS' if completed.returncode==0 and len(cases)==11 and not failed and not skipped else 'FAIL')
    finally:
        if started_container:subprocess.run(['docker','rm','-f',container],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
        if created_network:subprocess.run(['docker','network','rm',network],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
        output.write_text(json.dumps(result,indent=2)+'\n')
    return result


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--image',required=True);parser.add_argument('--expected-commit',required=True)
    parser.add_argument('--tests',type=Path,default=Path(__file__).resolve().parents[2]/'tests');parser.add_argument('--output',type=Path,required=True);args=parser.parse_args(argv)
    result=run(args.image,args.expected_commit,args.tests,args.output);print(json.dumps(result));return 0 if result['status']=='PASS' else 2


if __name__=='__main__':raise SystemExit(main())
