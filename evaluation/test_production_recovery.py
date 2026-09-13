import pytest
from scripts.production_recovery import contents


def test_snapshot_comparison_ignores_row_order_but_detects_values_and_counts():
    header = 'COPY jobsearch.jobs (id, title) FROM stdin;\n'
    a = header + '1\talpha\n2\tbeta\n\\.\n'
    b = header + '2\tbeta\n1\talpha\n\\.\n'
    assert contents(a) == contents(b)
    assert contents(a) != contents(a.replace('beta', 'changed'))
    assert contents(a) != contents(header + '1\talpha\n\\.\n')


def test_snapshot_parser_rejects_incomplete_or_missing_data():
    for value in ('', 'COPY jobsearch.jobs (id) FROM stdin;\n1\n'):
        with pytest.raises(ValueError): contents(value)


def test_sequence_comparison_detects_last_value_and_called_flag():
    from scripts.production_recovery import sequence_values
    a="SELECT pg_catalog.setval('jobsearch.sources_id_seq', 12, true);"
    assert sequence_values(a)=={'jobsearch.sources_id_seq':(12,True)}
    assert sequence_values(a)!=sequence_values(a.replace('12','13'))
    assert sequence_values(a)!=sequence_values(a.replace('true','false'))
    with pytest.raises(ValueError):sequence_values(a+'\n'+a)
    with pytest.raises(ValueError):sequence_values("SELECT pg_catalog.setval('x', bad);")

def test_privilege_comparison_ignores_comments_not_permissions():
    from scripts.production_recovery import privilege_statements
    a='-- source\nGRANT SELECT ON TABLE jobsearch.jobs TO jobsearch_app;'
    assert privilege_statements(a)==privilege_statements(a.replace('-- source','-- target'))
    assert privilege_statements(a)!=privilege_statements(a.replace('SELECT','UPDATE'))
