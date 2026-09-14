 'use client';
import {useEffect,useState} from 'react';
import {Database,RefreshCw,Network} from 'lucide-react';
import './data-quality.css';
type Model={status:string;generated_at?:string;metadata?:{tables:number;foreign_keys:number;engine:string;scope:string}};
export default function DataModel({version}:{version:number}){
 const [data,setData]=useState<Model|null>(null),[error,setError]=useState(''),[refresh,setRefresh]=useState(0),[busy,setBusy]=useState(false);
 useEffect(()=>{const controller=new AbortController();setBusy(true);setError('');setData(null);fetch('/api/data-model',{cache:'no-store',signal:controller.signal}).then(async r=>{if(!r.ok)throw new Error(r.status===403?'Operator access is required.':'Data model is unavailable.');return r.json()}).then(setData).catch(e=>{if(!controller.signal.aborted)setError(e.message)}).finally(()=>{if(!controller.signal.aborted)setBusy(false)});return()=>controller.abort()},[version,refresh]);
 return <section className="dq" aria-label="PostgreSQL data model"><div className="dq-hero"><Network size={38}/><div><span className="eyebrow">POSTGRESQL · PRODUCTION</span><h2>Explore your database structure</h2><p>SchemaSpy tables, columns and declared relationships. Generated from an empty copy of the production schema.</p></div><button className="secondary" disabled={busy} onClick={()=>setRefresh(n=>n+1)}><RefreshCw size={16} className={busy?'spin':''}/>Reload snapshot</button></div>
 {error&&<p role="alert" className="message error">{error}</p>}
 {busy&&<p role="status">Loading the latest generated model…</p>}
 {data?.status==='not_generated'&&<p className="empty">No model has been generated yet. Run the production diagram generator.</p>}
 {data?.status==='ready'&&<><div className="dq-summary"><article><span>Engine</span><strong><Database size={20}/>SchemaSpy</strong></article><article><span>Tables</span><strong>{data.metadata?.tables}</strong></article><article><span>Declared foreign keys</span><strong>{data.metadata?.foreign_keys}</strong></article><article><span>Schema captured</span><strong style={{fontSize:16}}>{new Date(data.generated_at!).toLocaleString()}</strong></article></div>
 <p className="muted">Select Relationships in the report for the diagram, or a table for its columns and connections. Reload retrieves the last snapshot; regeneration is an operator CLI action. Views, routines, defaults, comments and application records are excluded. No inferred relationships.</p>
 <iframe key={String(version)+'-'+refresh} title="SchemaSpy PostgreSQL model" src="/api/data-model/report/index.html" sandbox="allow-scripts allow-same-origin" referrerPolicy="no-referrer" style={{width:'100%',height:'78vh',minHeight:600,border:'1px solid #ccd6e3',borderRadius:14,background:'#fff'}}/>
 </>}
 </section>
}
