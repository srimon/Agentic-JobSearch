"""Operator-only catalog verification metadata, without catalog credentials."""
from fastapi import APIRouter, Depends, HTTPException
from src.db.store import connection
from src.settings import settings

def create_router(operator):
    router=APIRouter(prefix='/api/governance')
    @router.get('')
    def report(user=Depends(operator)):
        if not settings().data_management_enabled:
            raise HTTPException(404,'Data management is disabled')
        with connection() as conn:
            if not conn.execute("SELECT to_regclass('jobsearch.governance_snapshot') AS name").fetchone()['name']:
                return {'status':'not_generated'}
            row=conn.execute('SELECT generated_at,report FROM jobsearch.governance_snapshot WHERE id=true').fetchone()
        return {'status':'ready',**row} if row else {'status':'not_generated'}
    return router
