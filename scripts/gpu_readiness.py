"""Read-only GPU headroom check; does not reserve a device or load models."""
import csv
import io
import json
import shutil
import subprocess


def numeric(value):
    try:
        number=int(value.strip())
        return number if number>=0 else None
    except (ValueError,AttributeError):return None


def parse(output):
    devices=[]
    for row in csv.reader(io.StringIO(output)):
        if len(row)!=6:continue
        name,driver,total,used,free,util=[x.strip() for x in row]
        total,used,free,util=map(numeric,(total,used,free,util))
        known=all(x is not None for x in (total,used,free,util))
        valid=known and used<=total and free<=total and util<=100
        state='unknown' if not valid else ('busy' if free<2048 or util>10 else 'candidate_for_benchmark')
        devices.append({'name':name,'driver':driver,'total_mib':total,'used_mib':used,'free_mib':free,'utilization_percent':util,'headroom':state})
    return devices


def collect():
    binary=shutil.which('nvidia-smi')
    if not binary:return {'status':'unavailable','devices':[],'gpu_enabled':False}
    try:
        result=subprocess.run([binary,'--query-gpu=name,driver_version,memory.total,memory.used,memory.free,utilization.gpu','--format=csv,noheader,nounits'],capture_output=True,text=True,timeout=10,check=True)
        devices=parse(result.stdout)
    except (OSError,subprocess.SubprocessError):devices=[]
    return {'status':'observed' if devices else 'unknown','devices':devices,'gpu_enabled':False,'container_access':'not_verified','note':'A snapshot is not a reservation. Require a verified CUDA container and measured model memory before enabling one GPU workload. Thresholds: at least 2048 MiB free and at most 10 percent utilization; these are conservative benchmark gates, not model requirements.'}


if __name__=='__main__':print(json.dumps(collect(),indent=2))
