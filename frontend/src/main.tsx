import React, { useEffect, useRef, useState } from 'react';
import { createRoot } from 'react-dom/client';
import './style.css';

type Scan = {id:string; barcode:string; device_id:string; created_at:string; synced_at:string|null; attempts:number; last_error:string|null};
type Listing = {total:number; pending:number; items:Scan[]};
type Submission = {id:string; barcode:string};
const STORAGE = 'mes-poc-unconfirmed-scan';
async function api<T>(path:string, init?:RequestInit):Promise<T> {
  const response = await fetch(`/api${path}`, {...init, signal:AbortSignal.timeout(10000)});
  if (!response.ok) throw new Error(`請求失敗 (${response.status})：${await response.text()}`);
  return response.json();
}
// crypto.randomUUID needs HTTPS on remote hosts; getRandomValues also works on LAN HTTP.
function uuid():string {
  const bytes = crypto.getRandomValues(new Uint8Array(16));
  bytes[6] = (bytes[6] & 15) | 64; bytes[8] = (bytes[8] & 63) | 128;
  const h = Array.from(bytes, x => x.toString(16).padStart(2,'0')).join('');
  return `${h.slice(0,8)}-${h.slice(8,12)}-${h.slice(12,16)}-${h.slice(16,20)}-${h.slice(20)}`;
}
function restore():Submission|null {
  try {const raw=localStorage.getItem(STORAGE); if(!raw)return null; const v=JSON.parse(raw); return typeof v.id==='string' && typeof v.barcode==='string'?v:null;} catch{return null;}
}
function App(){
 const [unconfirmed,setUnconfirmed]=useState<Submission|null>(restore);
 const [value,setValue]=useState(()=>restore()?.barcode ?? '');
 const [data,setData]=useState<Listing>({total:0,pending:0,items:[]});
 const [status,setStatus]=useState<{mac_online:boolean;device_id:string;mac_url:string}|null>(null);
 const [reachable,setReachable]=useState(false);
 const [busy,setBusy]=useState(false);
 const [message,setMessage]=useState('輸入條碼並按 Enter，資料會先保存在樹莓派。');
 const input=useRef<HTMLInputElement>(null);
 const submitting=useRef(false);
 async function refresh(){
  try{setData(await api<Listing>('/scans'));setReachable(true);}catch{setReachable(false);}
  try{setStatus(await api('/status'));}catch{setStatus(null);}
 }
 useEffect(()=>{let stopped=false; let timer:ReturnType<typeof setTimeout>; const poll=async()=>{await refresh();if(!stopped)timer=setTimeout(poll,2500);};void poll();return()=>{stopped=true;clearTimeout(timer);};},[]);
 async function submit(event:React.FormEvent){
  event.preventDefault();if(submitting.current || !value.trim())return;
  submitting.current=true;setBusy(true);
  const payload=unconfirmed ?? {id:uuid(),barcode:value};
  setUnconfirmed(payload);
  try{
   // Persist the ID before sending, so a lost response / page reload can safely retry.
   localStorage.setItem(STORAGE,JSON.stringify(payload));
   const saved=await api<Scan>('/scans',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload)});
   localStorage.removeItem(STORAGE);setUnconfirmed(null);setValue('');
   setMessage(saved.synced_at?'已存本機，且已同步至 Mac。':'已存本機，等待同步至 Mac。');void refresh();
  }catch(error){setMessage(`尚未確認保存成功，請按「重試這筆」：${String(error)}`);}
  finally{submitting.current=false;setBusy(false);setTimeout(()=>input.current?.focus(),0);}
 }
 return <main>
  <header><span className="eyebrow">MES · CONNECTION POC</span><h1>掃碼連線驗證</h1><p>本機先保存，連線後自動同步。</p></header>
  <section className="stats" aria-label="連線與資料狀態">
   <article><small>樹莓派服務</small><strong className={reachable?'good':'bad'}>{reachable?'已連線':'未連線'}</strong><span>{status?.device_id ?? '等待回應'}</span></article>
   <article><small>Mac 後端</small><strong className={status?.mac_online?'good':'bad'}>{status ? (status.mac_online?'已連線':'離線'):'確認中'}</strong><span>{status?.mac_url ?? '—'}</span></article>
   <article><small>本機紀錄</small><strong>{data.total}</strong><span>{data.pending} 筆待同步{!reachable?'（上次讀取）':''}</span></article>
  </section>
  <section className="card"><form onSubmit={submit}><label htmlFor="barcode">條碼 / 測試文字</label><div className="entry"><input id="barcode" ref={input} autoFocus autoComplete="off" maxLength={512} value={value} readOnly={busy || !!unconfirmed} onChange={e=>setValue(e.target.value)} placeholder="例如 001234567890"/><button disabled={busy || !value.trim()}>{busy?'保存中…':unconfirmed?'重試這筆':'送出'}</button></div></form><p role="status">{unconfirmed&&!busy?'有一筆尚未確認的輸入；重試會沿用相同 ID。 ':''}{message}</p></section>
  <section className="card"><div className="section-heading"><div><h2>最近輸入</h2><small>顯示最近 100 筆 · 自動更新</small></div><button className="secondary" onClick={async()=>{try{await api('/sync',{method:'POST'});setMessage('已排程重試同步。');void refresh();}catch(e){setMessage(String(e));}}}>立即重試同步</button></div>
  <div className="table-wrap"><table><thead><tr><th>條碼內容</th><th>建立時間</th><th>同步狀態</th><th>嘗試次數</th></tr></thead><tbody>{data.items.map(row=><tr key={row.id}><td className="barcode" title={row.id}>{row.barcode}</td><td>{new Date(row.created_at).toLocaleString()}</td><td><span className={row.synced_at?'badge good':'badge pending'}>{row.synced_at?'已同步':row.last_error?'同步異常・將重試':'待同步'}</span>{row.last_error&&<details><summary>錯誤資訊</summary>{row.last_error}</details>}</td><td>{row.attempts}</td></tr>)}</tbody></table>{!data.items.length&&<p className="empty">{reachable?'尚無紀錄，先輸入一筆測試資料。':'正在等待樹莓派服務回應。'}</p>}</div></section>
  <footer>掃描槍鍵盤模式：聚焦輸入框，掃描後以 Enter 送出。</footer>
 </main>;
}
createRoot(document.getElementById('root')!).render(<App/>);
