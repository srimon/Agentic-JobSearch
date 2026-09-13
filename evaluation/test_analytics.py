import uuid
from datetime import datetime,timezone
from src.pipelines.analytics import changes,project

def row():return {'id':str(uuid.uuid4()),'source':'Public Co','provider':'greenhouse','level':'director','match_status':'match','availability':'observed_open','posted_at':None,'last_seen_at':'2026-09-13T10:00:00+00:00','url':'https://example.com/jobs/1','resume':'SECRET','description':'DO NOT EXPORT'}
def test_projection_excludes_private_and_raw_fields():
 result=project(row())
 assert not {'resume','description','url','email','title'} & result.keys()
 assert result['posted_at'] is None

def test_incremental_change_and_removal():
 original=row();state,delta=changes([original],{},1)
 assert len(delta)==1
 same,delta=changes([original],state,2);assert delta==[]
 original['level']='vp';new,delta=changes([original],state,3)
 assert len(delta)==1 and delta[0]['version']==3
 empty,delta=changes([],new,4)
 assert empty=={} and delta[0]['deleted']==1

def test_duplicate_ids_and_naive_dates_fail():
 import pytest
 value=row()
 with pytest.raises(ValueError):changes([value,value],{},1)
 value['last_seen_at']='2026-09-13T10:00:00'
 with pytest.raises(ValueError):project(value)

def test_api_requires_operator_and_rejects_production(monkeypatch):
 from fastapi import FastAPI,HTTPException
 from fastapi.testclient import TestClient
 from types import SimpleNamespace
 from src.api import analytics
 def deny():raise HTTPException(403,'Operator required')
 app=FastAPI();app.include_router(analytics.create_router(deny))
 assert TestClient(app).get('/api/analytics').status_code==403
 monkeypatch.setattr(analytics,'settings',lambda:SimpleNamespace(database_url='postgresql://localhost/jobsearch'))
 app=FastAPI();app.include_router(analytics.create_router(lambda: {'roles':['operator']}))
 assert TestClient(app).get('/api/analytics').status_code==404
