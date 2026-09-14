'use client';
import {useEffect,useState} from 'react';
type Run={day?:string;phase?:string;updated_at?:string;reason?:string;delivery?:string;source_counts?:Record<string,number>;counts?:Record<string,number>};
type State={schedule:string;next_run_at:string;latest:Run|null;history:Run[]};
const label=(text:string)=>text.replaceAll('_',' ');
const date=(value?:string)=>value?new Date(value).toLocaleString('en-US',{timeZone:'America/Los_Angeles'})+' PT':'Not recorded';
export default function DailyWorkflow(){
 const [data,setData]=useState<State|null>(null),[error,setError]=useState('');
 useEffect(()=>{let active=true;const load=()=>fetch('/api/workflow',{cache:'no-store'}).then(async r=>{if(!r.ok)throw Error('Workflow status unavailable. Check your sign-in.');return r.json()}).then(d=>{if(active){setData(d);setError('')}}).catch(e=>{if(active)setError(e.message)});load();const timer=setInterval(load,30000);return()=>{active=false;clearInterval(timer)}},[]);
 return <section className="obs-panel"><h2>Daily workflow</h2><p>Discovery → local resume checks → email report. No employer submissions.</p>{error&&<p role="alert">{error}</p>}{data?<>
 <p><strong>{data.schedule}</strong> · Next scheduled start: {date(data.next_run_at)}</p>
 <h3>{data.latest?label(data.latest.phase||'unknown'):'No workflow record yet'}</h3><p>{data.latest?.reason||'The first scheduled run will appear here.'}</p>
 <p>Last update: {date(data.latest?.updated_at)}</p>
 <div className="metrics">{Object.entries(data.latest?.source_counts||{}).map(([key,value])=><article key={key}><small>{label(key)}</small><strong>{value}</strong></article>)}</div>
 <h3>Preparation</h3><p>{Object.entries(data.latest?.counts||{}).map(([key,value])=>`${label(key)}: ${value}`).join(' · ')||'No preparation counts recorded.'}</p>
 <p>Delivery: {data.latest?.delivery==='smtp_accepted'?'SMTP accepted; inbox delivery is not independently verified.':'No new SMTP acceptance recorded for this workflow.'}</p>
 <h3>Recent progress</h3><ul>{data.history.slice(0,12).map((run,i)=><li key={i}>{date(run.updated_at)} — {label(run.phase||'unknown')}: {run.reason}</li>)}</ul>
 </>:!error&&<p>Loading workflow status…</p>}</section>
}
