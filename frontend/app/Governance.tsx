'use client';
import {useEffect,useState} from 'react';
import {BookOpen,ExternalLink,RefreshCw} from 'lucide-react';
import './data-quality.css';
import {joinUrl,useHubLinks} from './session';
type Snapshot={status:string;generated_at?:string;report?:{postgres_tables:number;clickhouse_assets:number;lineage_edges:number;scope:string;ml_asset:string}};
export default function Governance(){
 const [data,setData]=useState<Snapshot|null>(null),[error,setError]=useState(''),[refresh,setRefresh]=useState(0);
 useEffect(()=>{const c=new AbortController();setError('');fetch('/api/governance',{cache:'no-store',signal:c.signal}).then(async r=>{if(!r.ok)throw new Error(r.status===403?'Operator access is required.':'Catalog verification is unavailable.');return r.json()}).then(setData).catch(e=>{if(e.name!=='AbortError')setError(e.message)});return()=>c.abort()},[refresh]);
 const report=data?.report;
 const {links,operator}=useHubLinks(),catalog=operator?links.governance:undefined;
 return <section className="dq" aria-label="Data governance"><div className="dq-hero"><BookOpen size={38}/><div><span className="eyebrow">OPENMETADATA</span><h2>Understand and govern your data</h2><p>Explore the catalog, declared data lineage and business definitions.</p></div><button className="secondary" onClick={()=>setRefresh(n=>n+1)}><RefreshCw size={16}/>Reload verification</button></div>
 {error&&<p role="alert" className="message error">{error}</p>}{!data&&!error&&<p>Loading catalog verification…</p>}{data?.status==='not_generated'&&<p>The catalog has not been verified yet.</p>}
 {report&&<><div className="dq-summary"><article><span>PostgreSQL tables</span><strong>{report.postgres_tables}</strong></article><article><span>ClickHouse tables and views</span><strong>{report.clickhouse_assets}</strong></article><article><span>Verified lineage edges</span><strong>{report.lineage_edges}</strong></article><article><span>Ownership</span><strong>Assignment pending</strong></article></div><p>Verified {new Date(data!.generated_at!).toLocaleString()} · {report.scope}</p><p>Lineage follows PostgreSQL jobs and sources into the reconciled ClickHouse snapshot, current listings and ML feature view.</p>{catalog&&<a className="secondary" href={joinUrl(catalog,'table/'+encodeURIComponent(report.ml_asset)+'/lineage')} target="_blank" rel="noopener noreferrer">Open feature lineage <ExternalLink size={16}/></a>}</>}
 {catalog?<p><a className="primary" href={catalog} target="_blank" rel="noopener noreferrer">Open OpenMetadata <ExternalLink size={16}/></a></p>:<p>The OpenMetadata console is reachable on the private network only.</p>}<p>Use your separate governance account. Reload reads the last verification and does not run catalog ingestion.</p><p className="muted">No sample records or profiles are imported. Review suggested sensitivity tags and the proposed stewardship group before adopting them; catalog labels do not enforce database access. GX, Soda and dbt results remain in Data Quality.</p></section>
}
