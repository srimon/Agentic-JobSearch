from contextlib import contextmanager
from types import SimpleNamespace
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from src.api import analytics,data_quality,data_model
@pytest.mark.parametrize('module,path',[(analytics,'/api/analytics'),(data_quality,'/api/data-quality'),(data_model,'/api/data-model')])
def test_explicit_production_opt_in(module,path,monkeypatch):
 @contextmanager
 def connection():
  class Result:
   def fetchone(self):return {'name':None}
  yield SimpleNamespace(execute=lambda *a,**kw:Result())
 monkeypatch.setattr(module,'connection',connection)
 cfg=SimpleNamespace(database_url='postgresql://localhost/jobsearch',data_management_enabled=False)
 monkeypatch.setattr(module,'settings',lambda:cfg)
 app=FastAPI();app.include_router(module.create_router(lambda:{'roles':['operator']}));client=TestClient(app)
 assert client.get(path).status_code==404
 cfg.data_management_enabled=True
 result=client.get(path);assert result.status_code==200
 assert result.json().get('status','not_generated')=='not_generated'
