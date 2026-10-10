"""Exercise real ASGI routes with an isolated DB and fake source, no httpx needed."""

import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


class BatchApiTests(unittest.TestCase):
    def test_routes_and_background_boundary(self):
        temp_root = ROOT / "work" / "test-batch-api"
        temp_root.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=temp_root) as temporary:
            code = r'''
import asyncio, json
from pathlib import Path
from fastapi import BackgroundTasks
from app import main
from collector.batch_sources import SourcePage
from collector.models import CollectedJob

profile = {'schema_version':1,'education':{'level':'bachelor','related_major':False},'relevant_experience_years':0,'verified_tools':['Codex'],'project_count':1}
main.CANDIDATE_FIT_PROFILE_PATH.parent.mkdir(parents=True)
main.CANDIDATE_FIT_PROFILE_PATH.write_text(json.dumps(profile),encoding='utf-8')
options={'source_keys':['moka:deeproute'],'directions':['tools'],'per_source_limit':10,'staging_limit':5,'include_uncertain':False}
responses=[]
calls=[]
def fake_fetch(key, limit):
    assert responses[-1]['type']=='http.response.body', 'network must run after the 202 response'
    calls.append(key)
    return SourcePage([CollectedJob(title='AI 工具开发',description='使用 Codex 开发自动化内部工具。任职要求：本科及以上，专业不限，经验不限。',source_id='mock_local')],1,1,False,[])
main.BATCH_COLLECTOR.fetch=fake_fetch

async def request(path, method='GET', data=None):
    responses.clear()
    content=json.dumps(data).encode() if data is not None else b''
    async def receive(): return {'type':'http.request','body':content,'more_body':False}
    async def send(event): responses.append(event)
    await main.app({'type':'http','asgi':{'version':'3.0'},'http_version':'1.1','method':method,
        'scheme':'http','path':path,'raw_path':path.encode(),'query_string':b'',
        'root_path':'','headers':[(b'content-type',b'application/json')],
        'client':('127.0.0.1',12345),'server':('127.0.0.1',8000)},receive,send)
    return responses[0]['status'],json.loads(b''.join(e.get('body',b'') for e in responses))

async def test():
    status,schedule=await request('/api/collector/schedule')
    assert status==200 and not schedule['enabled'] and not schedule['runner_running']
    status,_=await request('/api/collector/schedule','PUT',{'interval_minutes':5,'options':options})
    assert status==400 and not calls
    status,_=await request('/api/collector/schedule','PUT',{'interval_minutes':360,'options':{**options,'source_keys':['boss_zhipin']}})
    assert status==400 and not calls
    status,_=await request('/api/collector/schedule','PUT',{'interval_minutes':'360','options':options})
    assert status==422 and not calls
    async with main.lifespan(main.app):
        status,schedule=await request('/api/collector/schedule','PUT',{'interval_minutes':360,'options':options})
        assert status==200 and schedule['enabled'] and schedule['runner_running'] and not calls
        from datetime import datetime,timezone
        assert (datetime.fromisoformat(schedule['next_run_at'])-datetime.now(timezone.utc)).total_seconds()>21500
        status,schedule=await request('/api/collector/schedule/pause','POST')
        assert status==200 and not schedule['enabled'] and schedule['next_run_at'] is None and not calls
        assert schedule['options']==options
        persisted=json.loads(main.COLLECTION_SCHEDULER.path.read_text(encoding='utf-8'))
        assert not persisted['enabled'] and persisted['options']==options
    assert not main.COLLECTION_SCHEDULER.state()['runner_running']
    status,data=await request('/api/collector/batch')
    assert status==200 and len(data['sources'])>=1
    status,_=await request('/api/collector/batch/runs','POST',{**options,'per_source_limit':101})
    assert status==422 and not calls
    status,_=await request('/api/collector/batch/runs','POST',{**options,'source_keys':['boss_zhipin']})
    assert status==400 and not calls
    status,run=await request('/api/collector/batch/runs','POST',options)
    assert status==202 and len(calls)==1
    status,detail=await request('/api/collector/batch/runs/'+run['id'])
    assert status==200 and detail['status']=='completed' and detail['counts']['added']==1
    status,_=await request('/api/collector/batch/runs','POST',options)
    assert status==409 and len(calls)==1
    status,_=await request('/api/collector/batch/runs/missing')
    assert status==404
    import sqlite3
    with sqlite3.connect(main.DB_PATH) as connection:
        assert connection.execute('SELECT COUNT(*) FROM jobs').fetchone()[0]==0
    print('ASGI API + lifespan + schedule + background + no formal import: OK')
asyncio.run(test())
'''
            result = subprocess.run([sys.executable, "-c", code], cwd=ROOT / "backend",
                env={**os.environ, "DATA_DIR": temporary, "PYTHONUTF8": "1", "PYTHONDONTWRITEBYTECODE": "1"},
                capture_output=True, encoding="utf-8", timeout=30)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
