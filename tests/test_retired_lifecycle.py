from scripts import lifecycle

def test_retired_marker_prevents_legacy_start_and_stop(tmp_path,monkeypatch):
 monkeypatch.setattr(lifecycle,'ROOT',tmp_path)
 (tmp_path/'.compose-retired').touch()
 monkeypatch.setattr(lifecycle,'command',lambda *a,**kw:(_ for _ in ()).throw(AssertionError('Docker must not be called')))
 assert lifecycle.execute('start')==0
 assert lifecycle.execute('stop')==0
