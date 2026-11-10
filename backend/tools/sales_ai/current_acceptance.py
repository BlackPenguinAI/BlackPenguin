"""Execute the agreed 64-case registry; mocks never imply live acceptance."""
import argparse,hashlib,json,os,subprocess,sys,uuid
from pathlib import Path
DEFAULT_MATRIX=Path(__file__).resolve().parents[2]/'tests/fixtures/sales_ai/current_acceptance64.json'


def validate(matrix,backend):
    if matrix.get('version')!='sales-current-acceptance/1.0' or [c.get('id') for c in matrix.get('cases',[])]!=list(range(1,65)):raise ValueError('Require exactly 64 ordered agreed case IDs.')
    for c in matrix['cases']:
        if not c.get('title') or not c.get('semantic_outcome') or not c.get('forbidden_effects'):raise ValueError('Missing semantic conditions.')
        if c['id']!=57 and not c.get('regression_nodes'):raise ValueError('Each deterministic case needs executable references.')
        for node in c['regression_nodes']:
            parts=node.split('::');path=(backend/parts[0]).resolve()
            if len(parts)!=2 or not parts[0].startswith('tests/test_') or not path.is_relative_to(backend.resolve()) or not path.is_file() or not parts[1].startswith('test_'):raise ValueError('Invalid regression node.')
    return matrix


def case_status(prefixes,results):
    if not prefixes:return 'NOT_RUN'
    statuses=[]
    for prefix in prefixes:
        values=[v for k,v in results.items() if k==prefix or k.startswith(prefix+'[')]
        statuses.append('FAIL' if 'FAIL' in values else 'NOT_RUN' if not values or any(v!='PASS' for v in values) else 'PASS')
    return 'FAIL' if 'FAIL' in statuses else 'NOT_RUN' if 'NOT_RUN' in statuses else 'PASS'


class Recorder:
    def __init__(self):self.results={};self.collection_errors=0;self.collected=[]
    def pytest_collection_finish(self,session):self.collected=[item.nodeid for item in session.items]
    def pytest_runtest_logreport(self,report):
        value='FAIL' if report.failed else 'NOT_RUN' if report.skipped else 'PASS' if report.when=='call' else None
        if value and self.results.get(report.nodeid)!='FAIL':self.results[report.nodeid]=value
    def pytest_collectreport(self,report):
        if report.failed:self.collection_errors+=1


def run(matrix_path,output,mode='prepare'):
    backend=Path(__file__).resolve().parents[2];raw=matrix_path.read_bytes();matrix=validate(json.loads(raw),backend)
    prefixes=sorted({n for c in matrix['cases'] for n in c['regression_nodes']});results={};exit_code=None
    output.parent.mkdir(parents=True,exist_ok=True)
    if mode=='regression':
        evidence=output.with_suffix('.pytest.json');nonce=uuid.uuid4().hex
        if evidence.exists():evidence.unlink()
        with output.with_suffix('.log').open('w') as log:
            p=subprocess.run([sys.executable,'-m','tools.sales_ai.current_acceptance','--worker','--run-id',nonce,'--matrix',str(matrix_path.resolve()),'--output',str(evidence.resolve())],cwd=backend,stdout=log,stderr=subprocess.STDOUT)
        exit_code=p.returncode
        if evidence.exists():
            data=json.loads(evidence.read_text())
            if data.get('run_id')==nonce:
                results={n:'NOT_RUN' for n in data.get('collected',[])};results.update(data.get('results') or {})
            else:exit_code=2
    cases=[]
    for c in matrix['cases']:
        cases.append({**c,'regression':{'status':case_status(c['regression_nodes'],results),'evidence':[{'node':n,'status':s} for n,s in results.items() if any(n==p or n.startswith(p+'[') for p in c['regression_nodes'])]},'real_model':{'status':'NOT_RUN'},'real_channels':{'sms':'NOT_RUN','whatsapp':'NOT_RUN'},'business_acceptance':'NOT_RUN'})
    status='FAIL' if exit_code not in {None,0} or any(c['regression']['status']=='FAIL' for c in cases) else 'REGRESSION_COMPLETE_LIVE_ACCEPTANCE_PENDING' if mode=='regression' else 'PREPARED_NOT_RUN'
    if mode=='regression' and status!='FAIL' and any(c['id']!=57 and c['regression']['status']!='PASS' for c in cases):status='REGRESSION_INCOMPLETE'
    sources=sorted([*backend.joinpath('app').rglob('*.py'),*backend.joinpath('tools/sales_ai').rglob('*.py')])
    tree={str(p.relative_to(backend)):hashlib.sha256(p.read_bytes()).hexdigest() for p in sources}
    report={'version':'sales-current-acceptance-results/1.0','mode':mode,'status':status,'matrix_sha256':hashlib.sha256(raw).hexdigest(),'candidate_commit':os.environ.get('APP_COMMIT_SHA') or None,'runtime_tree_sha256':hashlib.sha256(json.dumps(tree,sort_keys=True).encode()).hexdigest(),'runtime_file_count':len(tree),'regression_exit_code':exit_code,'provider_calls':0,'model_quality_evaluated':False,'production_acceptance_proven':False,'tests_sha256':{n.split('::')[0]:hashlib.sha256((backend/n.split('::')[0]).read_bytes()).hexdigest() for n in prefixes},'summary':{k:sum(c['regression']['status']==k for c in cases) for k in ['PASS','FAIL','NOT_RUN']},'cases':cases,'limitations':['Scripted contracts do not prove model understanding of every paraphrase.','Case 57 and real SMS/WhatsApp acceptance require observed model/provider results and operator review.']}
    output.write_text(json.dumps(report,indent=2,ensure_ascii=False)+'\n');return report


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--mode',choices=['prepare','regression'],default='prepare');parser.add_argument('--matrix',type=Path,default=DEFAULT_MATRIX);parser.add_argument('--output',type=Path,required=True);parser.add_argument('--worker',action='store_true',help=argparse.SUPPRESS);parser.add_argument('--run-id',help=argparse.SUPPRESS);args=parser.parse_args(argv)
    if args.output.resolve()==args.matrix.resolve():parser.error('Keep the matrix unchanged.')
    if args.worker:
        import pytest
        matrix=validate(json.loads(args.matrix.read_text()),Path(__file__).resolve().parents[2]);recorder=Recorder()
        code=pytest.main(['-q','--disable-warnings','--tb=short',*sorted({n for c in matrix['cases'] for n in c['regression_nodes']})],plugins=[recorder])
        args.output.write_text(json.dumps({'run_id':args.run_id,'exit_code':code,'collection_errors':recorder.collection_errors,'collected':recorder.collected,'results':recorder.results},indent=2)+'\n');return code
    result=run(args.matrix,args.output,args.mode);print(json.dumps({'status':result['status'],'summary':result['summary'],'model_quality_evaluated':False}));return 2 if result['status'] in {'FAIL','REGRESSION_INCOMPLETE'} else 0


if __name__=='__main__':raise SystemExit(main())
