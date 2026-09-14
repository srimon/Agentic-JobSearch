"""Compare trusted previous-release source with this release in a disposable DB.

Requires JOBSEARCH_AUTH_TEST=1 and current_database()=jobsearch_auth_test.
The baseline directory must contain trusted main.py and learning.py exported
from the previous reviewed Git commit. Never pass downloaded/untrusted code.
All fixture data is generated here; no production data or credentials are used.
"""
import argparse
import ast
import json
import os
import statistics
import time
import types
from contextlib import contextmanager
from pathlib import Path

from src.api import main
from src.applications.private import private_connection
from src.db.store import connection


def run(baseline):
    if os.environ.get('JOBSEARCH_AUTH_TEST')!='1':
        raise RuntimeError('Disposable database flag required')
    with connection() as c:
        if c.execute('SELECT current_database() name').fetchone()['name']!='jobsearch_auth_test':
            raise RuntimeError('Refusing to seed a non-test database')
        c.execute('TRUNCATE jobsearch.users,jobsearch.sources CASCADE')
        uid=c.execute("INSERT INTO jobsearch.users(issuer,subject,roles) VALUES('local','ranking-benchmark',ARRAY['member']) RETURNING id").fetchone()['id']
        source=c.execute("INSERT INTO jobsearch.sources(company,provider,board) VALUES('Fixture','ashby','fixture') RETURNING id").fetchone()['id']
        c.execute("""INSERT INTO jobsearch.jobs(id,source_id,source_job_id,company,title,location,work_mode,country_status,level,match_status,reason,description,url,content_hash,posted_at)
            SELECT md5('benchmark-'||n)::uuid,%s,n::text,'Fixture',
            CASE WHEN n%%3=0 THEN 'Director Data Engineering AI' ELSE 'Director Analytics' END,
            'US','Remote','us_based','Director','match','Fixture','Generated fixture',
            'https://example.com/benchmark/'||n,'fixture',now()-(n%%30)*interval '1 day'
            FROM generate_series(1,1500) n""",(source,))
        c.execute("""INSERT INTO jobsearch.job_archives(user_id,identity,job_id,final_status)
            SELECT %s,url,id,'applied' FROM jobsearch.jobs WHERE source_job_id::int<=300""",(uid,))
    previous=types.ModuleType('trusted_previous_learning')
    exec(compile((baseline/'learning.py').read_text(),str(baseline/'learning.py'),'exec'),previous.__dict__)
    tree=ast.parse((baseline/'main.py').read_text())
    function=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='jobs')
    function.decorator_list=[]
    namespace=dict(main.__dict__)
    namespace['learning_model']=previous.current
    exec(compile(ast.Module(body=[function],type_ignores=[]),'trusted_previous_jobs','exec'),namespace)
    old_jobs=namespace['jobs']
    metrics={}

    @contextmanager
    def measured(owner):
        with private_connection(owner) as c:
            class Proxy:
                def execute(self,q,p=None):
                    metrics['statements']+=1
                    cursor=c.execute(q,p)
                    class Cursor:
                        def fetchone(self): return cursor.fetchone()
                        def fetchall(self):
                            rows=cursor.fetchall()
                            if q.startswith('SELECT j.id'):metrics['job_rows']+=len(rows)
                            if 'a.feedback_reason' in q:metrics['feedback_rows']+=len(rows)
                            return rows
                    return Cursor()
            yield Proxy()
    main.private_connection=measured
    namespace['private_connection']=measured
    kwargs=dict(q='',date='any',level='',mode='',view='matches',page=1,show_dismissed=False,
                user={'id':uid,'roles':['member']},sort='recommended')
    result={}
    expected=None
    # Warm both paths before collecting seven interleaved samples each.
    samples={name:[] for name in ('previous','candidate')}
    for iteration in range(8):
        for name,handler in (('previous',old_jobs),('candidate',main.jobs)):
            metrics.update(statements=0,job_rows=0,feedback_rows=0)
            start=time.perf_counter()
            response=handler(**kwargs)
            elapsed=(time.perf_counter()-start)*1000
            ids=[str(r['id']) for r in response['items']]
            if expected is None:expected=ids
            assert ids==expected and response['total']==1200
            if iteration:samples[name].append(elapsed)
            result[name]={**metrics,'returned_rows':len(ids)}
    for name,values in samples.items():
        result[name].update(samples=len(values),median_ms=round(statistics.median(values),2),max_ms=round(max(values),2))
    result['fixture']={'jobs':1500,'archived_decisions':300,'eligible':1200,'rank_order_equal':True}
    print(json.dumps(result,sort_keys=True))
    return result


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--baseline',type=Path,required=True)
    run(parser.parse_args().baseline)
