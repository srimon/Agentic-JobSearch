 'use client';
import {useEffect,useState} from 'react';
import {ShieldCheck,Database,CheckCircle2,TriangleAlert,RefreshCw,PlugZap} from 'lucide-react';
import './data-quality.css';
type Check={id:string;title:string;severity:string;status:string;observed:number|null;expected:string;action:string};
type Run={id:string;started_at:string;finished_at:string|null;status:string;report:{checks?:Check[];engine_version?:string;contract_version?:string;error?:string;snapshot_at?:string}};
type History={workload:string;execution:string;runs:Run[]};
export default function DataQuality({version}:{version:number}){
 const [data,setData]=useState<History|null>(null),[error,setError]=useState(''),[selected,setSelected]=useState(''),[busy,setBusy]=useState(false),[refresh,setRefresh]=useState(0);
 useEffect(()=>{let active=true;const controller=new AbortController();async function load(){setBusy(true);try{const r=await fetch('/api/data-quality',{cache:'no-store',signal:controller.signal});if(!r.ok)throw new Error(r.status===403?'Operator access is required.':'Quality history is unavailable.');const d=await r.json();if(active){setData(d);setError('');}}catch(e){if(active)setError((e as Error).message)}finally{if(active)setBusy(false)}}load();const timer=setInterval(load,15000);return()=>{active=false;controller.abort();clearInterval(timer)}},[version,refresh]);
 const run=data?.runs.find(r=>r.id===selected)||data?.runs[0];const checks=run?.report.checks||[];const passed=checks.filter(c=>c.status==='passed').length;const failed=checks.filter(c=>c.status==='failed').length;
 return <section className="dq" aria-label="Data quality"><div className="dq-hero"><ShieldCheck size={38}/><div><span className="eyebrow">TRUST THROUGH EVIDENCE</span><h2>Know the quality of your job feed</h2><p>Versioned rules, measured results and clear next steps. Source dates stay unchanged.</p></div><button className="secondary" onClick={()=>setRefresh(n=>n+1)} disabled={busy}><RefreshCw size={16} className={busy?'spin':''}/>Refresh results</button></div>
 <div className="dq-integrations"><span><Database size={18}/>Great Expectations · active</span><span><PlugZap size={18}/>Soda · adapter reserved</span><span><PlugZap size={18}/>Slack · delivery disabled</span></div>
 {error&&<p role="alert" className="message error">{error}</p>}
 <div className="dq-summary"><article><span>Workload</span><strong>{data?.workload||'Loading…'}</strong></article><article><span>Checks passed</span><strong><CheckCircle2 size={22}/>{run?.status==='completed'?passed:'—'}</strong></article><article><span>Findings</span><strong><TriangleAlert size={22}/>{run?.status==='completed'?failed:'—'}</strong></article><article><span>Run status</span><strong>{run?.status||'Not run'}</strong></article></div>
 <p className="muted">Runs after a public-feed refresh or through the operator CLI. This page refreshes results every 15 seconds; refreshing does not start a validation.</p>
 {data&&!data.runs.length&&<div className="empty">No validation has run yet. No quality score is inferred.</div>}
 {run&&<><div className="dq-run"><label>Validation history<select value={run.id} onChange={e=>setSelected(e.target.value)}>{data?.runs.map(r=><option key={r.id} value={r.id}>{new Date(r.started_at).toLocaleString()} · {r.status}</option>)}</select></label><p>Snapshot: {run.report.snapshot_at?new Date(run.report.snapshot_at).toLocaleString():'Pending'}<br/>GX {run.report.engine_version||'—'} · Rules {run.report.contract_version||'—'}</p></div>
 {run.status==='running'&&<p role="status"><RefreshCw size={16} className="spin"/> Validation in progress. Results appear when the bounded worker finishes.</p>}
 {run.status==='failed'&&<p role="alert" className="message error">Validation could not complete. {run.report.error||'Check the runner.'} This is not a passing result.</p>}
 <div className="table-wrap"><table><thead><tr><th>Check</th><th>Severity</th><th>Observed</th><th>Expected</th><th>Result</th></tr></thead><tbody>{checks.map(c=><tr key={c.id}><td><strong>{c.title}</strong><small>{c.action}</small></td><td>{c.severity}</td><td>{c.observed??'Unknown'}</td><td>{c.expected}</td><td><span className={'badge '+(c.status==='failed'?'warning':'')}>{c.status}</span></td></tr>)}</tbody></table></div></>}
 <p className="muted">Aggregate counts only. No resumes, demographic answers, raw failed rows or credentials. These checks do not replace prompt-injection controls, application permissions or archive locks.</p></section>
}
