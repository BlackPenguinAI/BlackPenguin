"""Only mounted in the isolated staging images; no test readiness override."""
import os
import sys
from guard import validate, attest, require, allowed_route, ADMIN


def bootstrap(engine):
    from sqlalchemy import inspect, text
    from app.db.postgres import Base, SessionLocal
    from app.db.schema import CURRENT_SCHEMA_VERSION, SchemaVersion
    from app.modules.users.models import User, UserRole
    from app.core.security import get_password_hash
    from app.modules.companies.models import Company
    from app.modules.projects.models import Project, ProjectProfile, ProjectPropertyType
    from app.modules.sales_crm.models import Lead
    from app.modules.sales_agent.models import SalesConversation
    from datetime import datetime, timezone
    with engine.begin() as c:
        # Serialize initial creation; on PostgreSQL all DDL + seed is atomic.
        c.execute(text('LOCK TABLE hei06a2_guard IN EXCLUSIVE MODE'))
        if attest(c,allow_fresh=True) is not None:
            require(inspect(c).has_table('schema_versions'), 'Missing existing schema')
            require(c.execute(text('SELECT 1 FROM schema_versions WHERE version=:v'),{'v':CURRENT_SCHEMA_VERSION}).scalar() == 1,'Schema marker mismatch')
            print('Persistent staging already initialized; no reseed.')
            return
        require(set(inspect(c).get_table_names()) == {'hei06a2_guard'}, 'Database is not empty')
        Base.metadata.create_all(c)
        from sqlalchemy.orm import Session
        with Session(bind=c, autoflush=False, join_transaction_mode='rollback_only') as db:
            db.add(SchemaVersion(version=CURRENT_SCHEMA_VERSION))
            db.add(User(email=ADMIN,hashed_password=get_password_hash(os.environ['FIRST_SUPERADMIN_PASSWORD']),role=UserRole.SUPERADMIN,is_active=True))
            db.add(Company(id='stg-company',name='Staging Synthetic Company',country_code='US',is_active=True)); db.flush()
            db.add(Project(id='stg-project',company_id='stg-company',name='Staging Test Homes',city='Test City',country='US',timezone='America/Lima',is_active=True,is_demo=True)); db.flush()
            db.add(ProjectProfile(id='stg-profile',project_id='stg-project',final_approved=True,profile_data={},field_states={}))
            now=datetime.now(timezone.utc).replace(tzinfo=None)
            for ref,name,price,bath in [('stg-van','Van Buren',325000,1),('stg-oak','Oakwood',340000,2)]:
                db.add(ProjectPropertyType(id=ref,project_id='stg-project',name=name,review_status='confirmed',bedrooms=3,bathrooms=bath,starting_price=price,currency='USD',available_units=2,inventory_updated_at=now,sort_order=bath))
            db.add(Lead(id='stg-lead',company_id='stg-company',project_id='stg-project',full_name='Synthetic Buyer',phone='+15550000001',consent_status='granted',is_opt_out=False,agent_status='paused',is_demo=True)); db.flush()
            db.add(SalesConversation(id='stg-conversation',company_id='stg-company',project_id='stg-project',lead_id='stg-lead',provider='telnyx',channel='sms',is_paused=True,continuity_json={'lead_id':'stg-lead','project_id':'stg-project','epoch':1}))
            db.flush()
            db.commit()
        c.execute(text('UPDATE hei06a2_guard SET candidate_commit=:sha'),{'sha':os.environ['APP_COMMIT_SHA']})
    print('Persistent staging initialized; no live jobs created.')


class ClosedIngress:
    def __init__(self, app): self.app=app
    async def __call__(self, scope, receive, send):
        from starlette.responses import JSONResponse
        if scope['type']=='websocket':
            await send({'type':'websocket.close','code':1008}); return
        if scope['type']=='http' and not allowed_route(scope['method'],scope['path']):
            await JSONResponse({'detail':'Blocked in closed persistent staging'},status_code=403)(scope,receive,send); return
        await self.app(scope,receive,send)


def main():
    if len(sys.argv)!=2 or sys.argv[1] not in {'bootstrap','api','sdk'}: raise SystemExit(2)
    mode=sys.argv[1]; validate()
    from app.db.postgres import engine
    from app.modules.hermes_sales_core.engine_selection import live_hermes_ready
    require(live_hermes_ready() is False,'Production gate unexpectedly open')
    with engine.connect() as c: attest(c,allow_fresh=mode=='bootstrap')
    import app.db.base  # register all ORM models in every process
    from sqlalchemy.orm import configure_mappers
    configure_mappers()
    if mode=='bootstrap': bootstrap(engine); return
    import uvicorn
    if mode=='api':
        from app.main import app
        # The existing API lifespan runs the real sales worker. Do NOT start
        # another sales worker or the onboarding worker in this closed release.
        uvicorn.run(ClosedIngress(app),host='0.0.0.0',port=8000,workers=1,proxy_headers=False,access_log=False)
    else:
        from app.modules.hermes_sales_core.sdk_service import app
        uvicorn.run(app,host='0.0.0.0',port=8080,workers=1,proxy_headers=False,access_log=False)

if __name__=='__main__':main()
