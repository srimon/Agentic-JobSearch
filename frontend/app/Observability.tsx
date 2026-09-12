'use client';
import {useEffect,useState} from 'react';
import {Activity,Flame,RefreshCw,Radio,ExternalLink,Maximize2} from 'lucide-react';
import './observability.css';
const graph=(expr:string)=>'query?g0.expr='+encodeURIComponent(expr)+'&g0.tab=graph&g0.range_input=24h';
const tools = {
 prometheus:{name:'Prometheus',icon:Flame,description:'Explore metrics, scrape targets and alert rules.',screens:[['API traffic',graph('jobsearch:api_requests:rate5m')],['API latency',graph('jobsearch:api_latency_seconds:p95_1h')],['Collection outcomes',graph('sum by (provider,outcome) (increase(jobsearch_collection_runs_total[1h]))')],['Queue',graph('jobsearch_queue_ready')],['Queries','query'],['Targets','targets'],['Alerts','alerts'],['Rules','rules']]},
 grafana:{name:'Grafana',icon:Radio,description:'Live Jobsearch dashboards, time ranges, metrics and logs.',screens:[['Operations','d/jobsearch-operations?kiosk&refresh=15s'],['API & services','d/jobsearch-services?kiosk&refresh=15s'],['Collection & decisions','d/jobsearch-collection?kiosk&refresh=15s'],['Sources & queue','d/jobsearch-sources?kiosk&refresh=15s'],['Logs','d/jobsearch-logs?kiosk&refresh=15s']]},
 phoenix:{name:'Phoenix',icon:Activity,description:'Inspect Jobsearch traces, spans and execution timing.',screens:[['Projects & traces','projects'],['GraphQL explorer','graphql?q='+encodeURIComponent('query JobsearchProjects { projects(first: 10) { edges { node { id name } } } }')]]}
};
type Tool=keyof typeof tools;
export default function Observability({version}:{version:number}){
 const [tool,setTool]=useState<Tool>('grafana'),[screen,setScreen]=useState(0),[reload,setReload]=useState(0),[loaded,setLoaded]=useState(false),[expanded,setExpanded]=useState(false),[error,setError]=useState(''),[ready,setReady]=useState(false);
 const current=tools[tool];const path=current.screens[screen]?.[1]||current.screens[0][1];const url='/api/monitoring/'+tool+'/'+path;
 useEffect(()=>{let cancelled=false;setLoaded(false);setReady(false);setError('');
 const check=async()=>{try{const r=await fetch('/api/monitoring-status/'+tool,{cache:'no-store'});if(!r.ok)throw new Error(r.status===401?'Your session has expired. Sign in again.':'Operator access is required.');const result=await r.json();if(!cancelled){setReady(result.available);setError(result.available?'':current.name+' is starting or unavailable. This page will retry automatically.')}}catch(e){if(!cancelled){setReady(false);setError((e as Error).message)}}};
 void check();const timer=setInterval(check,15000);return()=>{cancelled=true;clearInterval(timer)};
 },[tool,reload,version]);
 useEffect(()=>{setLoaded(false)},[url]);

 return <section className={'observability-panel '+(expanded?'obs-expanded':'')} aria-label="Observability tools">
 <div className="obs-intro"><div><span className="eyebrow">LIVE OPERATIONS</span><h2>Your agents, in view</h2><p>Full monitoring interfaces, connected to your isolated Jobsearch services.</p></div></div>
 <div className="obs-tabs" role="tablist" aria-label="Monitoring tool">{(Object.keys(tools) as Tool[]).map(key=>{const Icon=tools[key].icon;return <button key={key} role="tab" aria-selected={tool===key} className={'obs-tool '+key+(tool===key?' selected':'')} onClick={()=>{setTool(key);setScreen(0)}}><Icon/><span><strong>{tools[key].name}</strong><small>{tools[key].description}</small></span></button>})}</div>
 <div className="obs-controls"><div className="obs-screen-buttons">{current.screens.map(([label],index)=><button className={screen===index?'primary':'secondary'} key={label} onClick={()=>{setScreen(index);setReload(n=>n+1)}}>{label}</button>)}</div><button className="secondary" onClick={()=>setReload(n=>n+1)}><RefreshCw size={16}/>Reload</button><button className="secondary" onClick={()=>setExpanded(!expanded)}><Maximize2 size={16}/>{expanded?'Exit expanded view':'Expand'}</button><a href={url} target="_blank" rel="noreferrer"><ExternalLink size={16}/>Open full view</a></div>
 {(!loaded||error)&&<p role="status">{error||'Loading '+current.name+'…'}</p>}
 {ready&&<iframe key={url+reload+version} src={url} title={current.name+' live interface'} className="obs-vendor-frame" onLoad={()=>setLoaded(true)} referrerPolicy="no-referrer"/>}
 <p className="muted small">Operator access required. Monitoring changes are blocked; use the tool’s time range and refresh controls to explore current data. A trace does not confirm an application was submitted.</p>
 </section>
}
