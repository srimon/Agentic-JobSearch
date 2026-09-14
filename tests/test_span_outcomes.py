from unittest.mock import MagicMock
import pytest
from opentelemetry.trace import StatusCode
from src import observability

@pytest.mark.parametrize('failure',[None,ValueError('private upstream payload'),OSError('private address')])
def test_fetch_span_records_outcome_without_exception_payload(monkeypatch,failure):
    tracer=MagicMock();span=tracer.start_as_current_span.return_value.__enter__.return_value
    monkeypatch.setattr(observability.trace,'get_tracer',lambda name:tracer)
    monkeypatch.setattr(observability,'event',MagicMock())
    duration=MagicMock();monkeypatch.setattr(observability,'DURATION',duration)
    run={'source_id':7,'provider':'dice','id':'test-run'}
    def collect():
        with observability.collection_span(run):
            if failure:raise failure
    if failure:
        with pytest.raises(type(failure)) as caught:collect()
        assert caught.value is failure
    else:collect()
    tracer.start_as_current_span.assert_called_once_with('source.collect',record_exception=False,set_status_on_exception=False)
    span.set_status.assert_called_once_with(StatusCode.ERROR if failure else StatusCode.OK)
    span.record_exception.assert_not_called()
    assert 'private' not in repr(span.method_calls)
    span.set_attribute.assert_any_call('collection.phase','fetch')
    if failure:span.set_attribute.assert_any_call('error.type',type(failure).__name__)
    duration.labels.return_value.observe.assert_called_once()
