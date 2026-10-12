"""Real HTTP + real SQLite tests; uses temp DBs and never touches your scans."""
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import time
import unittest
from uuid import uuid4
import httpx

BASE = Path(__file__).resolve().parent
MES = Path(os.environ.get('MES_SOURCE', str(BASE.parents[1] / 'mes')))

def port():
    with socket.socket() as s:
        s.bind(('127.0.0.1', 0))
        return s.getsockname()[1]

class Integration(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.mp, self.pp = port(), port()
        self.mac = f'http://127.0.0.1:{self.mp}'
        self.pi = f'http://127.0.0.1:{self.pp}'
        self.processes = []
        self.client = httpx.Client(timeout=5, trust_env=False)
        self.mac_proc = self.start(MES, self.mp, 'mac')
        self.pi_proc = self.start(BASE, self.pp, 'pi')

    def start(self, folder, p, name):
        env = {**os.environ, 'DB_PATH': str(Path(self.tmp.name)/f'{name}.db'),
               'MAC_API_URL': self.mac, 'SYNC_INTERVAL_SECONDS': '1'}
        proc = subprocess.Popen([sys.executable, '-m', 'uvicorn', 'app:app', '--host', '127.0.0.1', '--port', str(p)], cwd=folder, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        self.processes.append(proc)
        self.wait_for(lambda: self.client.get(f'http://127.0.0.1:{p}/api/health').status_code == 200)
        return proc

    def wait_for(self, fn):
        until = time.monotonic()+15
        while time.monotonic()<until:
            try:
                if fn(): return
            except httpx.TransportError: pass
            time.sleep(.1)
        self.fail('Timed out waiting for expected state')

    def stop(self, proc):
        proc.terminate()
        proc.wait(timeout=10)

    def tearDown(self):
        for proc in self.processes:
            if proc.poll() is None: self.stop(proc)
        self.client.close()
        self.tmp.cleanup()

    def test_offline_restart_replay_and_validation(self):
        payload = {'id': str(uuid4()), 'barcode': '001234'}
        first = self.client.post(self.pi+'/api/scans', json=payload)
        self.assertEqual(first.status_code, 200)
        self.wait_for(lambda: self.client.get(self.pi+'/api/scans').json()['pending'] == 0)
        self.assertEqual(self.client.get(self.mac+'/api/scans').json()['items'][0]['barcode'], '001234')
        # Lost-ack replay at Mac: same ID, same data must not duplicate.
        incoming = {k:first.json()[k] for k in ('id','barcode','device_id','created_at')}
        for _ in range(3):
            self.assertEqual(self.client.post(self.mac+'/api/scans',json=incoming).status_code, 200)
            self.assertEqual(self.client.post(self.pi+'/api/scans',json=payload).status_code, 200)
        self.assertEqual(self.client.get(self.mac+'/api/scans').json()['total'],1)
        self.assertEqual(self.client.post(self.pi+'/api/scans',json={**payload,'barcode':'different'}).status_code,409)
        self.assertEqual(self.client.post(self.mac+'/api/scans',json={**incoming,'barcode':'different'}).status_code,409)
        for bad in ['', '   ', 'x'*513]:
            self.assertEqual(self.client.post(self.pi+'/api/scans',json={'id':str(uuid4()),'barcode':bad}).status_code,422)
        self.assertEqual(self.client.post(self.pi+'/api/scans',json={'id':'bad','barcode':'x'}).status_code,422)
        self.stop(self.mac_proc)
        for _ in range(3):
            self.assertEqual(self.client.post(self.pi+'/api/scans',json={'id':str(uuid4()),'barcode':'001234'}).status_code,200)
        self.wait_for(lambda: any(x['last_error'] for x in self.client.get(self.pi+'/api/scans').json()['items']))
        self.assertEqual(self.client.get(self.pi+'/api/scans').json()['pending'],3)
        self.assertFalse(self.client.get(self.pi+'/api/status').json()['mac_online'])
        self.stop(self.pi_proc)
        self.pi_proc = self.start(BASE,self.pp,'pi')
        self.assertEqual(self.client.get(self.pi+'/api/scans').json()['pending'],3)
        self.mac_proc = self.start(MES,self.mp,'mac')
        self.wait_for(lambda: self.client.get(self.pi+'/api/scans').json()['pending']==0)
        self.assertEqual(self.client.get(self.mac+'/api/scans').json()['total'],4)
        self.assertEqual(self.client.get(self.pi+'/api/scans').json()['total'],4)
        self.assertEqual(self.client.get(self.pi+'/').status_code,200)

if __name__ == '__main__': unittest.main(verbosity=2)
