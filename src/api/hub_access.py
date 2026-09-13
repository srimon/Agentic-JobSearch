"""Scoped compatibility authorization for the private library gateway."""
from fastapi import APIRouter,Depends,HTTPException,Request,Response
from src.db.store import connection,audit
ALLOWED_ORIGINS={'http://localhost:3001','http://localhost:3011','http://localhost:8000','http://localhost:8010'}

def create_router(operator):
    router=APIRouter()
    @router.get('/api/hub/library-authorize')
    def authorize(request:Request,user=Depends(operator)):
        method=request.headers.get('x-original-method','GET').upper()
        if method not in {'GET','HEAD','OPTIONS','POST','PUT','PATCH','DELETE'}:raise HTTPException(403,'Unsupported method')
        if method not in {'GET','HEAD','OPTIONS'}:
            if request.headers.get('x-original-origin') not in ALLOWED_ORIGINS:raise HTTPException(403,'Origin rejected')
            with connection() as conn:
                audit(conn,str(user['id']),'hub.library.authorize','library',details={'method':method})
        return Response(status_code=204,headers={'X-Hub-User':str(user['id']),'Cache-Control':'no-store'})
    return router
