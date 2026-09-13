 'use client';
import {useEffect,useState} from 'react';
import {Database,RefreshCw,ExternalLink} from 'lucide-react';
import './data-quality.css';
type Bucket={label:string;count:number|string};
type Report={engine:string;scope:string;totals:{listings:number|string;unique_urls:number|string;unknown_dates:number|string};windows:Record<string,{total:number|string;sources:Bucket[];roles:Bucket[];dates:Bucket[]}>;sources:{total:number;errors:number;stale:number;last_success:string|null};changed_rows:number;checks:string};
type Snapshot={status:string;generated_at?:string;report?:Report};
function Bars({title,rows}:{title:string;rows:Bucket[]}){const max=Math.max(1,...rows.map(x=>Number(x.count)));return <article className="analytics-chart"><h3>{title}</h3>{rows.length?rows.map(row=><div className="analytics-bar" key={row.label}><div><span>{row.label}</span><strong>{row.count}</strong></div><div className="analytics-track"><span style={{width:(Number(row.count)/max*100)+'%'}}/></div></div>):<p>No listings in this window.</p>}</article>}
export default function Analytics({version}:{version:number}){
 const [snapshot,setSnapshot]=useState<Snapshot|null>(null),[error,setError]=useState(''),[window,setWindow]=useState('24h'),[refresh,setRefresh]=useState(0);
 useEffect(()=>{const controller=new AbortController();setError('');fetch('/api/analytics',{cache:'no-store',signal:controller.signal}).then(async r=>{if(!r.ok)throw new Error(r.status===403?'Operator access is required.':'Analytics snapshot is unavailable.');return r.json()}).then(setSnapshot).catch(e=>{if(e.name!=='AbortError')setError(e.message)});return()=>controller.abort()},[version,refresh]);
 const report=snapshot?.report,selected=report?.windows[window];const stale=snapshot?.generated_at?Date.now()-Date.parse(snapshot.generated_at)>26*3600000:false;
 return <section className="dq" aria-label="Jobsearch analytics"><div className="dq-hero"><Database size={36}/><div><span className="eyebrow">CLICKHOUSE · JOBSEARCH STAGING</span><h2>Public job-feed analytics</h2><p>Listing counts, role coverage and source freshness from a reconciled ClickHouse snapshot.</p></div><button className="secondary" onClick={()=>setRefresh(x=>x+1)}><RefreshCw size={16}/>Reload snapshot</button></div>
 {error&&<p role="alert" className="message error">{error}</p>}
 <label>Posting window <select value={window} onChange={e=>setWindow(e.target.value)}><option value="24h">Past 24 hours</option><option value="7d">Past 7 days</option><option value="all">All posting dates</option></select></label>
 {!snapshot&&!error&&<p>Loading analytics…</p>}{snapshot?.status==='not_generated'&&<p>No ingestion snapshot has been generated yet.</p>}
 {report&&selected&&<><p>Snapshot: {snapshot?.generated_at?new Date(snapshot.generated_at).toLocaleString():'Unknown'} · reconciliation {report.checks}</p>{stale&&<p role="status" className="message">This snapshot is over 26 hours old. Run the ingestion pipeline to refresh it.</p>}
 <div className="dq-summary"><article><span>Listings in window</span><strong>{selected.total}</strong></article><article><span>All public listing rows</span><strong>{report.totals.listings}</strong></article><article><span>Distinct exact URLs · all dates</span><strong>{report.totals.unique_urls}</strong></article><article><span>Unknown posting dates</span><strong>{report.totals.unknown_dates}</strong></article></div>
 <div className="analytics-grid"><Bars title="Listings by source" rows={selected.sources}/><Bars title="Listings by role level" rows={selected.roles}/><Bars title="Listings by posting date · latest 31 days represented" rows={selected.dates}/></div>
 <div className="dq-summary"><article><span>Configured sources · all</span><strong>{report.sources.total}</strong></article><article><span>Sources with errors</span><strong>{report.sources.errors}</strong></article><article><span>Not refreshed within 7 days</span><strong>{report.sources.stale}</strong></article><article><span>Changed rows in ingestion</span><strong>{report.changed_rows}</strong></article></div>
 <p className="muted">Includes match and review classifications in the public staging feed, not personal application statuses. Date windows use employer posting dates at snapshot time; unknown dates appear only in All posting dates. Reload reads the saved snapshot and does not start ingestion.</p></>}
 <a className="secondary" href="http://localhost:3187/play" target="_blank" rel="noopener noreferrer">Open ClickHouse console <ExternalLink size={16}/></a></section>
}
