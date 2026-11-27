"""Only mounted in the isolated staging images; no test readiness override."""
import os
import sys
from guard import validate, attest, require, allowed_route, ADMIN
from startup_evidence import event


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


def _check_upload_root(root, uid, gid):
    """Verify storage identity and perform the same mkdir as the company service."""
    import tempfile
    require(root.is_dir() and not root.is_symlink(), 'Missing private uploads mount')
    info = root.stat()
    require((info.st_uid, info.st_gid) == (uid, gid) and (info.st_mode & 0o777) == 0o700, 'Wrong uploads ownership or mode')
    receipts = root / 'receipts'
    require(not receipts.is_symlink(), 'Unexpected receipts symlink')
    receipts.mkdir(exist_ok=True)
    # Test a real write, not os.access; remove the test file automatically.
    with tempfile.TemporaryFile(dir=receipts) as probe:
        probe.write(b'hei06a2')
        probe.flush()


def check_api_storage():
    """Exercise the legacy relative receipts path as the running API user."""
    from pathlib import Path
    require(Path.cwd() == Path('/app'), 'Unexpected API working directory')
    require(os.geteuid() == 10001 and os.getegid() == 10001, 'Unexpected API identity')
    _check_upload_root(Path('uploads'), 10001, 10001)


class ClosedIngress:
    def __init__(self, app): self.app=app
    async def __call__(self, scope, receive, send):
        from starlette.responses import JSONResponse
        if scope['type']=='websocket':
            await send({'type':'websocket.close','code':1008}); return
        if scope['type']=='http' and not allowed_route(scope['method'],scope['path']):
            await JSONResponse({'detail':'Blocked in closed persistent staging'},status_code=403)(scope,receive,send); return
        if scope['type']=='lifespan':
            event('api_lifespan','BEGIN')
            async def observed_send(message):
                if message['type']=='lifespan.startup.complete':event('api_lifespan','PASS')
                elif message['type']=='lifespan.startup.failed':event('api_lifespan','FAIL',reason='startup_failed')
                await send(message)
            try:
                await self.app(scope,receive,observed_send)
            except Exception as exc:
                event('api_lifespan','FAIL',exc=exc)
                raise
            return
        await self.app(scope,receive,send)


def main():
    if len(sys.argv)!=2 or sys.argv[1] not in {'bootstrap','api','sdk'}: raise SystemExit(2)
    mode=sys.argv[1]
    phase='environment'
    def begin(name):
        nonlocal phase
        phase=name;event(phase,'BEGIN')
    def done():event(phase,'PASS')
    try:
        begin('environment');validate();done()
        begin('database_import')
        from app.db.postgres import engine
        done()
        begin('production_gate')
        from app.modules.hermes_sales_core.engine_selection import live_hermes_ready
        require(live_hermes_ready() is False,'Production gate unexpectedly open');done()
        begin('database_identity')
        with engine.connect() as c: attest(c,allow_fresh=mode=='bootstrap')
        done()
        begin('register_orm')
        import app.db.base
        from sqlalchemy.orm import configure_mappers
        configure_mappers();done()
        if mode=='bootstrap':
            begin('bootstrap');bootstrap(engine);done();return
        import uvicorn
        if mode=='api':
            begin('api_storage');check_api_storage();done()
            begin('api_import')
            from app.main import app
            done()
            # Exercise the exact application readiness function before binding.
            # No schema bypass, no mocked health endpoint, no additional worker.
            begin('api_schema')
            from app.modules.health.router import readiness
            readiness();done()
            begin('api_serve')
            uvicorn.run(ClosedIngress(app),host='0.0.0.0',port=8000,workers=1,proxy_headers=False,access_log=False,lifespan='on')
        else:
            begin('sdk_import')
            from app.modules.hermes_sales_core.sdk_service import app
            done();begin('sdk_serve')
            uvicorn.run(app,host='0.0.0.0',port=8080,workers=1,proxy_headers=False,access_log=False,lifespan='on')
    except Exception as exc:
        reason=None
        if phase=='api_schema':
            detail=getattr(exc,'detail',None)
            if isinstance(detail,dict):reason=detail.get('reason')
        event(phase,'FAIL',exc=exc,reason=reason)
        raise SystemExit(1) from None

if __name__=='__main__':main()
