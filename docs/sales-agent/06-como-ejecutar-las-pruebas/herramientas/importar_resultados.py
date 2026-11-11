"""Import only explicit synthetic server archives, with whitelisted conversation fields."""
import argparse,csv,hashlib,json,re,zipfile
from pathlib import Path


CASE_LABELS={'first_time_A': 'primera-compra-pdf-y-visita', 'first_time_B': 'inicial-financiacion-y-rechazo', 'move_up_A': 'vivienda-mayor-galeria-y-visita', 'move_up_B': 'cambio-de-propiedad-fotos-y-despedida', 'relocation_A': 'reubicacion-ubicacion-y-visita', 'relocation_B': 'vendedor-sin-asignacion', 'downsizing_A': 'vivienda-menor-pdf-y-visita', 'downsizing_B': 'fotos-ausentes-y-propiedad-agotada', 'rental_A': 'inversion-alquiler-y-visita', 'rental_B': 'rentabilidad-e-inventario-desconocidos', 'resale_A': 'reventa-y-visita', 'resale_B': 'financiacion-sin-pago-ni-reserva', 'portfolio_A': 'comparacion-y-eleccion-de-horario', 'portfolio_B': 'comparacion-sin-horarios', 'unknown_A': 'visita-sin-segmento', 'unknown_B': 'peticion-humana-y-cierre', 'human_record_then_question': 'peticion-humana-y-pregunta-posterior', 'farewell_then_reopen': 'despedida-y-retoma', 'lower_budget_financing': 'presupuesto-inferior-y-financiacion', 'property_reservation': 'sin-pago-ni-separacion-en-chat'}

def export(source,root):
    prior_runs=root/'05-resultados-y-mejoras/corridas.json'
    prior_index=root/'04-conversaciones/indice.json'
    runs=json.loads(prior_runs.read_text()) if prior_runs.exists() else []
    index=json.loads(prior_index.read_text()) if prior_index.exists() else []
    review_path=root/'04-conversaciones/revisiones-humanas.json'
    reviews=json.loads(review_path.read_text()) if review_path.exists() else {}
    files=sorted(p for p in Path(source).glob('sales-*.zip') if re.fullmatch(r'sales-(?:booking-point-\d+|commercial-point-\d+|closing-point-\d+|compact-battery-\d+|compact-repair-\d+)\.zip',p.name))
    for order,path in enumerate(files):
        with zipfile.ZipFile(path) as archive:
            report=json.loads(archive.read('summary.json' if 'summary.json' in archive.namelist() else 'report.json'))
        if not report.get('synthetic_only') or report.get('production_database_writes',0) or report.get('lead_contacts',0):raise ValueError('Only isolated synthetic evidence may be published.')
        key=path.stem
        runs=[r for r in runs if r['run']!=key]
        index=[i for i in index if i['run']!=key]
        compact=key.startswith('sales-compact');suite='compact' if compact else 'booking' if 'booking' in key else 'commercial' if 'commercial' in key else 'closing'
        case_ids=sorted(c['case'] for c in report['cases']);cohort=hashlib.sha256(json.dumps(case_ids).encode()).hexdigest()[:12]
        cases=[]
        for case in report['cases']:
            if not re.fullmatch(r'[A-Za-z0-9_]{1,80}',case['case']):raise ValueError('Invalid synthetic case identifier.')
            checks=list(case.get('checks',[]))+[check for turn in case.get('turns',[]) for check in turn.get('checks',[])]
            failures=[c for c in checks if c['status']=='FAIL'];blocked=[c for c in checks if c['status'] in {'BLOCKED','NOT_RUN'}]
            status='fallido' if failures else 'incompleto' if blocked else 'aprobado'
            review=reviews.get(key+':'+case['case'],{'status':'pending','note':'Automatic approval is not a human judgment of conversational quality.'})
            folder='necesitan-mejoras' if status=='fallido' else 'pendientes-de-revision' if status=='incompleto' else 'funcionaron'
            if review['status']=='necesita-mejoras':folder='necesitan-mejoras'
            actions='-'.join(str(t.get('action','')) for t in case.get('turns',[]) if t.get('action'))
            label=CASE_LABELS.get(case['case'],case['case'].lower().replace('_','-'))
            name=f'{label}__{case["case"].lower().replace("_","-")}__{key}__{status}.json'
            if review['status']=='necesita-mejoras':name=name.replace('.json','__revision-necesita-mejoras.json')
            relative=Path('04-conversaciones')/folder/name
            turns=[]
            for turn in case.get('turns',[]):
                metadata=turn.get('output',{}).get('metadata',{});composition=metadata.get('composition',{})
                turns.append({'turn':turn.get('turn'),'action':turn.get('action'),'lead':turn.get('lead_message',turn.get('message',turn.get('inbound'))),'agent':turn.get('reply'),
                    'understanding':turn.get('input_trace',{}).get('understanding',turn.get('understanding')),'error_code':turn.get('error_code'),
                    'checks':turn.get('checks',[]),'composition':{'status':composition.get('status'),'attempts':[{k:a[k] for k in ('status','error_code','rule_code','validation_issues') if k in a} for a in composition.get('attempts',[])]}})
            document={'synthetic_only':True,'execution_origin':'server_submitted_synthetic_run','source_archive':path.name,'source_sha256':hashlib.sha256(path.read_bytes()).hexdigest(),'commit':report.get('commit'),'sales_model':report.get('sales_model'),
                'configuration_version':report.get('configuration_version'),'configuration_sha256':report.get('configuration_sha256'),'clock_utc':case.get('clock_utc'),'team':case.get('team',[]),'case':case['case'],'description':label,'persona':case.get('persona'),'company_id':report.get('company_id'),'project_id':case.get('project_id'),'property_type_id':case.get('property_type_id'),
                'automatic_result':status,'human_review':review,'stop_reason':case.get('stop_reason'),
                'expected_outcome':case.get('expected_outcome'),'topic_tags':sorted({t['action'] for t in turns if t['action']}),'turns':turns,'checks':case.get('checks',[]),'failures':failures,'blocked_checks':blocked,'meetings':case.get('meetings',[]),'materials':case.get('materials',[])}
            target=root/relative;target.parent.mkdir(parents=True,exist_ok=True);target.write_text(json.dumps(document,indent=2,ensure_ascii=False)+'\n')
            cases.append({'case':case['case'],'status':status,'meetings':len(case.get('meetings',[])),'turns':len(turns),'failures':len(failures)})
            index.append({'run':key,'case':case['case'],'status':status,'human_review':review['status'],'file':relative.as_posix()})
        usage=report.get('provider_usage',{});expected=report.get('expected_bookings')
        if expected is None:expected=3 if suite=='booking' else 0 if suite in {'commercial','closing'} else sum(c.get('expected_outcome')=='booked' for c in report['cases'])
        entry={'run':key,'execution_origin':'server_submitted_synthetic_run','archive':path.name,'sha256':hashlib.sha256(path.read_bytes()).hexdigest(),'commit':report.get('commit'),'suite':suite,'cohort':cohort,'selected_cases':case_ids,
            'model':report.get('sales_model'),'configuration_version':report.get('configuration_version'),'configuration_sha256':report.get('configuration_sha256'),'status':report.get('status'),'cases':len(cases),'approved_cases':sum(c['status']=='aprobado' for c in cases),
            'turns':sum(c['turns'] for c in cases),'expected_bookings':expected,'actual_bookings':sum(c['meetings'] for c in cases),'provider_calls':report.get('provider_calls'),
            'cost_usd_recorded':usage.get('cost_usd'),'cost_complete':report.get('cost_reporting_complete',usage.get('responses_with_cost')==report.get('provider_calls')),'checks_summary':report.get('summary'),'case_results':cases}
        runs.append(entry)
        destination=root/'05-resultados-y-mejoras'/key;destination.mkdir(parents=True,exist_ok=True);(destination/'resultado.json').write_text(json.dumps(entry,indent=2,ensure_ascii=False)+'\n')
        (destination/'README.md').write_text(f'# {key}\n\n[Volver a resultados](../README.md) · [Ver resultado JSON](resultado.json)\n\nCommit `{entry["commit"]}`. Estado original: **{entry["status"]}**. Casos: {entry["approved_cases"]}/{entry["cases"]} aprobados automáticamente. Visitas: {entry["actual_bookings"]}/{entry["expected_bookings"]}.\n\nEl costo registrado puede estar incompleto; consultar `cost_complete`. Estos resultados corresponden a simulaciones en el servidor, no a entregas reales por WhatsApp/SMS.\n')
    result=root/'05-resultados-y-mejoras';result.mkdir(parents=True,exist_ok=True)
    (result/'corridas.json').write_text(json.dumps(runs,indent=2,ensure_ascii=False)+'\n')
    (root/'04-conversaciones/indice.json').write_text(json.dumps(index,indent=2,ensure_ascii=False)+'\n')
    columns=['run','suite','cohort','cases','approved_cases','turns','expected_bookings','actual_bookings','provider_calls','cost_usd_recorded','cost_complete']
    with (result/'metricas.csv').open('w',newline='') as handle:
        writer=csv.DictWriter(handle,fieldnames=columns);writer.writeheader();writer.writerows({k:r[k] for k in columns} for r in runs)
    return runs,index

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--source',required=True);parser.add_argument('--output',required=True);args=parser.parse_args();export(args.source,Path(args.output))
