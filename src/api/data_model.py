"""Authenticated staging SchemaSpy snapshots; never exposes database credentials."""
import mimetypes
from urllib.parse import urlsplit
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from src.settings import settings
from src.db.store import connection

HEADERS={'Cache-Control':'no-store','X-Content-Type-Options':'nosniff','Referrer-Policy':'no-referrer',
 'Content-Security-Policy': "default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; font-src 'self' data:; connect-src 'none'; object-src 'self'; base-uri 'none'; form-action 'none'; frame-ancestors 'self'"}

def valid_path(path):
    return bool(path) and '\\' not in path and '%' not in path and not path.startswith('/') and all(p not in ('.','..','') for p in path.split('/')) and len(path)<512

def create_router(operator):
    router=APIRouter(prefix='/api/data-model')
    def staging():
        if urlsplit(settings().database_url).path!='/jobsearch_staging':raise HTTPException(404,'Data model is available in staging only')
    @router.get('')
    def metadata(user=Depends(operator)):
        staging()
        with connection() as conn:
            if not conn.execute("SELECT to_regclass('jobsearch.data_model_snapshot') AS name").fetchone()['name']:return {'status':'not_generated'}
            row=conn.execute('SELECT generated_at,metadata FROM jobsearch.data_model_snapshot WHERE id=true').fetchone()
        return {'status':'ready',**row} if row else {'status':'not_generated'}
    @router.get('/report/{path:path}')
    def asset(path:str,user=Depends(operator)):
        staging()
        if not valid_path(path):raise HTTPException(404,'Asset not found')
        with connection() as conn:
            if not conn.execute("SELECT to_regclass('jobsearch.data_model_assets') AS name").fetchone()['name']:raise HTTPException(404,'Data model has not been generated')
            row=conn.execute('SELECT body FROM jobsearch.data_model_assets WHERE path=%s',(path,)).fetchone()
        if not row:raise HTTPException(404,'Asset not found')
        media=mimetypes.guess_type(path)[0] or 'application/octet-stream'
        return Response(content=bytes(row['body']),media_type=media,headers=HEADERS)
    return router
