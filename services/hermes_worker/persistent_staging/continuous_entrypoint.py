"""Persistent staging API and private SDK, with ordinary ASGI worker lifespan."""
import sys
from guard import attest, require, ADMIN
from entrypoint import ClosedIngress, check_api_storage
from startup_evidence import event
from continuous_scope import check_process

PREFIX='/api/v1/staging/hermes'


def allowed_control(method,path):
    if method=='POST' and path in {PREFIX+'/grant',PREFIX+'/revoke',PREFIX+'/replay'}:return True
    from live_scope_policy import MESSAGES
    return (method=='POST' and path in {PREFIX+'/enqueue/'+c for c in MESSAGES}) or (method=='GET' and path in {PREFIX+'/job/'+c for c in MESSAGES}|{PREFIX+'/result'})


class StagingIngress(ClosedIngress):
    async def __call__(self,scope,receive,send):
        if scope['type']=='http' and allowed_control(scope['method'],scope['path']):
            await self.app(scope,receive,send);return
        await super().__call__(scope,receive,send)


def install_routes(app,engine,SessionLocal):
    from fastapi import APIRouter,Depends,HTTPException,Response
    from app.modules.auth.deps import RoleChecker
    from app.modules.users.models import User,UserRole
    from continuous_scope import seed,enqueue,requeue,revoke,status,job_snapshot
    from live_scope_policy import validate_case
    router=APIRouter(prefix=PREFIX,include_in_schema=False)
    staff=RoleChecker([UserRole.SUPERADMIN])
    def operator(actor: User=Depends(staff)):
        check_process('api')
        if actor.email!=ADMIN:raise HTTPException(403,'Staging operator required.')
        return actor
    def execute(fn,*args):
        try:return fn(*args)
        except Exception as exc:
            event('continuous_control','FAIL',exc=exc)
            raise HTTPException(409,'Scoped staging operation denied.') from None
    @router.post('/grant')
    def grant(actor=Depends(operator)):return execute(seed,engine,SessionLocal)
    @router.post('/enqueue/{case}')
    def submit(case:str,actor=Depends(operator)):
        execute(validate_case,case);return execute(enqueue,SessionLocal,case)
    @router.post('/replay')
    def replay(actor=Depends(operator)):return execute(requeue,SessionLocal,'first')
    @router.post('/revoke')
    def close(actor=Depends(operator)):return execute(revoke,SessionLocal)
    @router.get('/job/{case}')
    def job(case:str,response:Response,actor=Depends(operator)):
        response.headers['Cache-Control']='no-store'
        execute(validate_case,case);return execute(job_snapshot,case)
    @router.get('/result')
    def result(response:Response,actor=Depends(operator)):
        response.headers['Cache-Control']='no-store';return execute(status,SessionLocal)
    app.include_router(router)


def main():
    phase='environment'
    try:
        require(len(sys.argv)==2 and sys.argv[1] in ('api','sdk'),'continuous_role_required');role=sys.argv[1]
        check_process(role)
        from app.db.postgres import engine,SessionLocal
        phase='database_identity'
        with engine.connect() as db:attest(db)
        phase='register_orm'
        import app.db.base
        from sqlalchemy.orm import configure_mappers
        configure_mappers()
        import uvicorn
        if role=='api':
            phase='api_storage';check_api_storage()
            phase='api_import'
            from app.main import app
            install_routes(app,engine,SessionLocal)
            phase='api_schema'
            from app.modules.health.router import readiness
            readiness()
            phase='api_serve';event('api_serve','BEGIN')
            uvicorn.run(StagingIngress(app),host='0.0.0.0',port=8000,workers=1,proxy_headers=False,access_log=False,lifespan='on')
        else:
            phase='sdk_import'
            from app.modules.hermes_sales_core.sdk_service import app
            phase='sdk_serve';event('sdk_serve','BEGIN')
            uvicorn.run(app,host='0.0.0.0',port=8080,workers=1,proxy_headers=False,access_log=False,lifespan='on')
    except Exception as exc:
        event(phase,'FAIL',exc=exc);raise SystemExit(1) from None

if __name__=='__main__':main()
