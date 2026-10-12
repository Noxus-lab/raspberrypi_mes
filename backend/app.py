import asyncio
import logging
import os
from contextlib import asynccontextmanager, suppress
import httpx
from fastapi import FastAPI, HTTPException, Query
from fastapi.staticfiles import StaticFiles
from common import BASE, Scan, db, now

MAC_URL = os.getenv('MAC_API_URL', 'http://127.0.0.1:8000').rstrip('/')
DEVICE_ID = os.getenv('DEVICE_ID', 'pi5-01')
INTERVAL = max(1, float(os.getenv('SYNC_INTERVAL_SECONDS', '5')))
FRONTEND = (BASE / os.getenv('FRONTEND_DIST', '../frontend/dist')).resolve()
log = logging.getLogger('uvicorn.error')

def init_db():
    with db() as conn:
        conn.execute('PRAGMA journal_mode=WAL')
        conn.execute("""CREATE TABLE IF NOT EXISTS scans (
            id TEXT PRIMARY KEY, barcode TEXT NOT NULL, device_id TEXT NOT NULL,
            created_at TEXT NOT NULL, synced_at TEXT, attempts INTEGER NOT NULL DEFAULT 0,
            last_error TEXT)""")

async def sync_once(app):
    async with app.state.sync_lock:
        # Process each pending record at most once per pass; failures cannot starve later rows.
        with db() as conn:
            ids = [r[0] for r in conn.execute('SELECT id FROM scans WHERE synced_at IS NULL ORDER BY rowid')]
        for scan_id in ids:
            with db() as conn:
                row = dict(conn.execute('SELECT * FROM scans WHERE id=?', (scan_id,)).fetchone())
            try:
                payload = {k: row[k] for k in ('id', 'barcode', 'device_id', 'created_at')}
                response = await app.state.client.post(f'{MAC_URL}/api/scans', json=payload)
                response.raise_for_status()
                ack = response.json()
                if ack.get('id') != scan_id or ack.get('status') != 'stored':
                    raise ValueError('Mac 回應未確認這筆資料已保存')
                with db() as conn:
                    conn.execute('UPDATE scans SET synced_at=?, attempts=attempts+1, last_error=NULL WHERE id=?', (now(), scan_id))
            except (httpx.HTTPError, ValueError) as exc:
                with db() as conn:
                    conn.execute('UPDATE scans SET attempts=attempts+1, last_error=? WHERE id=?', (str(exc)[:500], scan_id))
                if isinstance(exc, httpx.TransportError):
                    break  # Host unavailable: do not wait for one timeout per pending scan.

async def worker(app):
    while True:
        app.state.wake.clear()
        try:
            await sync_once(app)
        except Exception:
            log.exception('同步失敗；保留待同步資料，下一輪重試')
        try:
            await asyncio.wait_for(app.state.wake.wait(), timeout=INTERVAL)
        except asyncio.TimeoutError:
            pass

@asynccontextmanager
async def lifespan(app):
    init_db()
    app.state.sync_lock = asyncio.Lock()
    app.state.wake = asyncio.Event()
    async with httpx.AsyncClient(timeout=3, trust_env=False) as client:
        app.state.client = client
        task = asyncio.create_task(worker(app))
        try:
            yield
        finally:
            task.cancel()
            with suppress(asyncio.CancelledError):
                await task

app = FastAPI(title='MES POC — Raspberry Pi', lifespan=lifespan)

@app.get('/api/health')
def health():
    with db() as conn:
        conn.execute('SELECT 1')
    return {'status': 'ok', 'service': 'raspberrypi', 'device_id': DEVICE_ID}

@app.post('/api/scans')
async def create(scan: Scan):
    scan_id = str(scan.id)
    with db() as conn:
        conn.execute('INSERT OR IGNORE INTO scans (id, barcode, device_id, created_at) VALUES (?, ?, ?, ?)', (scan_id, scan.barcode, DEVICE_ID, now()))
        row = dict(conn.execute('SELECT * FROM scans WHERE id=?', (scan_id,)).fetchone())
        if row['barcode'] != scan.barcode:
            raise HTTPException(409, '相同 ID 的內容不同，拒絕覆寫')
    app.state.wake.set()
    return row

@app.get('/api/scans')
def scans(limit: int = Query(100, ge=1, le=1000)):
    with db() as conn:
        rows = conn.execute('SELECT * FROM scans ORDER BY rowid DESC LIMIT ?', (limit,)).fetchall()
        total, pending = conn.execute('SELECT COUNT(*), COALESCE(SUM(synced_at IS NULL),0) FROM scans').fetchone()
    return {'total': total, 'pending': pending, 'items': [dict(row) for row in rows]}

@app.get('/api/status')
async def status():
    try:
        response = await app.state.client.get(f'{MAC_URL}/api/health')
        response.raise_for_status()
        body = response.json()
        online = body.get('service') == 'mes' and body.get('status') == 'ok'
    except (httpx.HTTPError, ValueError):
        online = False
    return {'device_id': DEVICE_ID, 'mac_online': online, 'mac_url': MAC_URL}

@app.post('/api/sync')
async def retry():
    app.state.wake.set()
    return {'status': 'scheduled'}

# API routes must be registered before the static mount.
if FRONTEND.is_dir():
    app.mount('/', StaticFiles(directory=FRONTEND, html=True), name='frontend')
