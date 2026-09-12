from scripts import gpu_readiness as gpu

def test_busy_gpu_is_not_a_benchmark_candidate():
    result=gpu.parse('NVIDIA GeForce GTX 1650 Ti,581.95,4096,3843,96,100')[0]
    assert result['headroom']=='busy'

def test_unavailable_and_invalid_numbers_remain_unknown():
    assert gpu.parse('GPU,driver,4096,100,N/A,N/A')[0]['headroom']=='unknown'
    assert gpu.parse('GPU,driver,4096,100,3000,101')[0]['headroom']=='unknown'
    assert gpu.parse('unexpected output')==[]

def test_headroom_is_only_a_benchmark_candidate():
    assert gpu.parse('GPU,driver,4096,1000,3000,0')[0]['headroom']=='candidate_for_benchmark'

def test_missing_gpu_does_not_enable_it(monkeypatch):
    monkeypatch.setattr(gpu.shutil,'which',lambda _:None)
    assert gpu.collect()=={'status':'unavailable','devices':[],'gpu_enabled':False}

def test_probe_does_not_request_processes_or_load_models(monkeypatch):
    monkeypatch.setattr(gpu.shutil,'which',lambda _:'/usr/bin/nvidia-smi')
    def run(args,**kwargs):
        assert args==['/usr/bin/nvidia-smi','--query-gpu=name,driver_version,memory.total,memory.used,memory.free,utilization.gpu','--format=csv,noheader,nounits']
        return gpu.subprocess.CompletedProcess(args,0,'GPU,driver,4096,1000,3000,0')
    monkeypatch.setattr(gpu.subprocess,'run',run)
    result=gpu.collect()
    assert result['gpu_enabled'] is False and result['container_access']=='not_verified'
