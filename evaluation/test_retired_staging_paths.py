import pytest
from scripts import jobsearch_staging


def test_retired_staging_never_defaults_to_production(monkeypatch):
    monkeypatch.delenv('JOBSEARCH_RETIRED_STAGING_KUBECONFIG', raising=False)
    monkeypatch.setattr(jobsearch_staging.subprocess, 'run', lambda *a, **k: pytest.fail('No subprocess without explicit staging configuration'))
    with pytest.raises(RuntimeError, match='Staging is retired'):
        jobsearch_staging.kubectl('get','pods')


def test_retired_staging_rejects_production_context(monkeypatch,tmp_path):
    config=tmp_path/'staging'; config.write_text('placeholder')
    monkeypatch.setenv('JOBSEARCH_RETIRED_STAGING_KUBECONFIG',str(config))
    from types import SimpleNamespace
    monkeypatch.setattr(jobsearch_staging.subprocess,'run',lambda *a,**k:SimpleNamespace(returncode=0,stdout='k3d-enterprise-hub\n'))
    with pytest.raises(RuntimeError, match='production is prohibited'):jobsearch_staging.staging_config()
