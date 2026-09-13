"""Operator-only aggregate quality history. No raw rows or execution endpoint."""
from urllib.parse import urlsplit
from fastapi import APIRouter, Depends, HTTPException
from src.settings import settings
from src.db.store import connection


def create_router(operator):
    router = APIRouter(prefix='/api/data-quality')

    @router.get('')
    def history(user=Depends(operator)):
        if urlsplit(settings().database_url).path != '/jobsearch_staging' and not getattr(settings(), 'data_management_enabled', False):
            raise HTTPException(404, 'Data management is disabled')
        with connection() as conn:
            if not conn.execute("SELECT to_regclass('jobsearch.quality_runs') AS name").fetchone()['name']:
                runs = []
            else:
                runs = conn.execute("SELECT id, started_at, finished_at, status, report FROM jobsearch.quality_runs ORDER BY started_at DESC LIMIT 30").fetchall()
        return {'workload': ('Jobsearch staging' if urlsplit(settings().database_url).path == '/jobsearch_staging' else 'Jobsearch production'), 'engine': 'GX / Soda / dbt',
                'adapters': {**{engine: ('verified' if any(r['status']=='completed' and r['report'].get('engine','gx')==engine for r in runs) else 'not_verified') for engine in ('gx','soda','dbt')}, 'slack':'disabled'},
                'execution': 'After public-feed refresh or operator CLI', 'runs': runs}
    return router
