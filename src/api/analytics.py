"""Operator-only ClickHouse-derived staging snapshots; no database secrets."""
from urllib.parse import urlsplit
from fastapi import APIRouter,Depends,HTTPException
from src.settings import settings
from src.db.store import connection

def create_router(operator):
 router=APIRouter(prefix='/api/analytics')
 @router.get('')
 def report(user=Depends(operator)):
  if urlsplit(settings().database_url).path!='/jobsearch_staging' and not getattr(settings(), 'data_management_enabled', False):raise HTTPException(404,'Data management is disabled')
  with connection() as c:
   if not c.execute("SELECT to_regclass('jobsearch.analytics_snapshot') AS name").fetchone()['name']:return {'status':'not_generated'}
   row=c.execute('SELECT generated_at,report FROM jobsearch.analytics_snapshot WHERE id=true').fetchone()
  return {'status':'ready',**row} if row else {'status':'not_generated'}
 return router
