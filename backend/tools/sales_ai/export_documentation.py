"""Export whitelisted synthetic fixtures to documentation; no model/provider calls."""
import argparse,json,tempfile
from datetime import datetime
from pathlib import Path


def export(output,clock):
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session
    import app.db.base
    from app.db.postgres import Base
    from app.core.config import settings
    from app.modules.users.models import User
    from app.modules.sales_crm.models import SalesAvailabilityBlock
    from .synthetic_fixtures import seed,PROJECTS,VERSION
    from .compact_battery import PERSONAS,SPECS,team
    root=Path(output);root.mkdir(parents=True,exist_ok=True)
    def save(name,data):
        path=root/name;path.parent.mkdir(parents=True,exist_ok=True)
        path.write_text(json.dumps({'synthetic_only':True,'fixture_version':VERSION,'clock_utc':clock.isoformat(),'data':data},indent=2,ensure_ascii=False,default=str)+'\n')
    engine=create_engine('sqlite://');Base.metadata.create_all(engine)
    prior=settings.PROJECT_UPLOAD_ROOT
    try:
        with tempfile.TemporaryDirectory() as tmp,Session(engine,autoflush=False) as db:
            settings.PROJECT_UPLOAD_ROOT=tmp+'/uploads'
            manifest=seed(db,Path(tmp)/'materials')
            save('02-datos-de-prueba/empresa-y-proyectos/empresa.json',{'id':manifest['company_id'],'name':manifest['company_name'],'country':'US','timezone':'UTC','fictional':True})
            projects=[];properties=[];resources=[]
            for project,spec in zip(manifest['projects'],PROJECTS):
                projects.append({k:v for k,v in project.items() if k!='properties'}|{'company_id':manifest['company_id'],'address':f'{len(projects)+1} Synthetic Avenue','approved':True,'payment_methods':['Cash','Bank financing'],'delivery':'December 2027','down_payment_terms':None,'guaranteed_returns':None})
                for prop,item in zip(project['properties'],spec['properties']):
                    properties.append({k:v for k,v in prop.items() if k!='resources'}|{'project_id':project['id'],'company_id':manifest['company_id'],'facts':item,'area_unit':'m²','currency':'USD' if item['price'] is not None else None})
                    resources.extend(dict(resource,project_id=project['id'],property_type_id=prop['id'],public_production_url=None,scope='disposable_lab_only') for resource in prop['resources'])
            save('02-datos-de-prueba/empresa-y-proyectos/proyectos.json',projects)
            save('02-datos-de-prueba/empresa-y-proyectos/propiedades.json',properties)
            save('02-datos-de-prueba/empresa-y-proyectos/galerias-y-documentos.json',resources)
            save('02-datos-de-prueba/leads/perfiles-de-leads.json',[dict(p,age=None,occupation=None,note='Age and occupation are not defined or used to infer a segment.') for p in PERSONAS])
            save('03-casos-de-prueba/casos-guionados.json',SPECS)
            users=[];assignments=[];slots=[]
            for key in SPECS:
                roster=team(db,manifest,key,clock)
                for row in roster:
                    user=db.get(User,row['id'])
                    users.append({k:row[k] for k in ('id','company_id','role','active','accepts_appointments','has_slots')}|{'scenario':key,'user_role':'sales','name':user.first_name+' '+user.last_name,'email':user.email,'login_enabled':False})
                    assignments.append({'scenario':key,'user_id':user.id,'company_id':user.company_id,'access_scope':row['access_scope'],'project_ids':row['project_ids'],'target_project_id':manifest['projects'][SPECS[key]['project']]['id']})
                    for slot in db.query(SalesAvailabilityBlock).filter_by(user_id=user.id):
                        slots.append({'scenario':key,'user_id':user.id,'starts_at_utc':slot.starts_at,'ends_at_utc':slot.ends_at,'timezone':slot.timezone})
            save('02-datos-de-prueba/vendedores-y-horarios/vendedores.json',users)
            save('02-datos-de-prueba/vendedores-y-horarios/asignaciones-a-proyectos.json',assignments)
            save('02-datos-de-prueba/vendedores-y-horarios/horarios-disponibles.json',slots)
    finally:
        settings.PROJECT_UPLOAD_ROOT=prior;engine.dispose()


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--output',required=True);parser.add_argument('--clock',default='2026-11-11T06:34:00')
    args=parser.parse_args();export(args.output,datetime.fromisoformat(args.clock))
