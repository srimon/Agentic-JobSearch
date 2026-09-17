'use client';
import {useEffect,useRef,useState} from 'react';
import {ExternalLink,RefreshCw,Maximize2} from 'lucide-react';
import './observability.css';
import './monitoring-console.css';
import PhoenixGraphQLDisplays from './PhoenixGraphQLDisplays';
import {apiFetch,apiPath} from './session';

const graph=(expr:string)=>'query?g0.expr='+encodeURIComponent(expr)+'&g0.tab=graph&g0.range_input=1d';
const staging=process.env.NEXT_PUBLIC_JOBSEARCH_ENVIRONMENT==='staging';
const tools={
 grafana:{name:'Grafana',description:'Dashboards over API health, collection runs and job discovery.',screens:[['API & Services','d/jobsearch-services?kiosk&refresh=15s'],['Operations','d/jobsearch-operations?kiosk&refresh=15s'],['Collection & Decisions','d/jobsearch-collection?kiosk&refresh=15s'],['Sources & Queue','d/jobsearch-sources?kiosk&refresh=15s'],...(!staging?[['Logs','d/jobsearch-logs?kiosk&refresh=15s']]:[])]},
 prometheus:{name:'Prometheus',description:'The raw metric series behind the dashboards.',screens:[['API request rate',graph('sum by (status) (rate(jobsearch_http_requests_total[5m]))')],['API p95 latency',graph('histogram_quantile(0.95, sum by (le) (rate(jobsearch_http_duration_seconds_bucket[5m])))')],['Queue',graph('jobsearch_queue_ready')],['Targets','targets'],['Alerts','alerts'],['Rules','rules']]},
 phoenix:{name:'Phoenix',description:'Recorded traces, spans and execution timing.',screens:[['Projects & Traces','projects'],['GraphQL Displays','graphql-displays'],['GraphQL Explorer','graphql?q='+encodeURIComponent('query JobsearchProjects { projects(first: 10) { edges { node { id name } } } }')]]}
};
type Tool=keyof typeof tools;
type Health='checking'|'up'|'down';

export default function Observability({version}:{version:number}){
 const [tool,setTool]=useState<Tool>('grafana'),[screen,setScreen]=useState(0),[reload,setReload]=useState(0);
 const [health,setHealth]=useState<Record<Tool,Health>>({grafana:'checking',prometheus:'checking',phoenix:'checking'});
 const [checked,setChecked]=useState(''),[error,setError]=useState(''),[loaded,setLoaded]=useState(false),[expanded,setExpanded]=useState(false),[height,setHeight]=useState(600);
 const frame=useRef<HTMLDivElement>(null);
 const current=tools[tool],selected=current.screens[screen]||current.screens[0],path=selected[1],custom=path==='graphql-displays';
 // The tools are served from the ROOT of every name this page is on, and each is configured for
 // that root (Grafana's root_url and Phoenix's host root path are /api/monitoring/<tool>): framed
 // under /jobsearch/api/monitoring/... Grafana's own router answered "Page not found" for every
 // dashboard (17 Sep 2026). The dashboard check below still goes through the API's own prefix.
 const url='/api/monitoring/'+tool+'/'+path;
 useEffect(()=>{
  let cancelled=false;
  const check=async()=>{
   const entries=await Promise.all((Object.keys(tools) as Tool[]).map(async key=>{
    try{const r=await apiFetch('/monitoring-status/'+key,{cache:'no-store'});const data=await r.json();return [key,r.ok&&data.available?'up':'down'] as const;}
    catch{return [key,'down'] as const;}
   }));
   if(!cancelled){setHealth(Object.fromEntries(entries) as Record<Tool,Health>);setChecked(new Date().toLocaleTimeString());}
  };
  void check();const timer=setInterval(check,15000);return()=>{cancelled=true;clearInterval(timer)};
 },[reload,version]);
 useEffect(()=>{
  setLoaded(custom);setError('');let cancelled=false;
  if(tool==='grafana'&&health.grafana==='up'){
   const uid=path.split('/')[1].split('?')[0];
   void apiFetch('/monitoring/grafana/api/dashboards/uid/'+uid,{cache:'no-store'}).then(r=>{
    if(!r.ok&&!cancelled)setError(r.status===404?'This dashboard has not been provisioned in this environment.':'The dashboard could not be opened. Check your session and administrator access.');
   }).catch(()=>{if(!cancelled)setError('The dashboard check could not reach the server.');});
  }
  return()=>{cancelled=true};
 },[url,custom,tool,path,reload,health.grafana]);
 useEffect(()=>{
  const measure=()=>{if(frame.current)setHeight(Math.max(480,window.innerHeight-frame.current.getBoundingClientRect().top-20));};
  const initial=requestAnimationFrame(measure),observer=new ResizeObserver(measure);observer.observe(document.body);window.addEventListener('resize',measure);
  return()=>{cancelAnimationFrame(initial);observer.disconnect();window.removeEventListener('resize',measure)};
 },[tool,expanded]);
 const choose=(key:Tool)=>{setTool(key);setScreen(0);setReload(n=>n+1)};
 return <section className={'observability-panel mbk-monitoring '+(expanded?'obs-expanded':'')} aria-label="Observability tools">
  <header className="monitor-heading"><div><span className="eyebrow">{'JOB SEARCH'}</span><h2>{tool==='phoenix'?'Explainability':'Observability'}</h2><p>{tool==='phoenix'?'Explore the recorded trace of each operation in Phoenix.':'Grafana dashboards and the Prometheus series they are drawn from.'}</p></div></header>
  <nav className="monitor-purpose" aria-label="Monitoring purpose"><button className={tool!=='phoenix'?'selected':''} onClick={()=>choose('grafana')}>Observability</button><button className={tool==='phoenix'?'selected':''} onClick={()=>choose('phoenix')}>Explainability · Phoenix</button></nav>
  {tool!=='phoenix'&&<div className="monitor-tools" role="tablist" aria-label="Monitoring tool">{(['grafana','prometheus'] as Tool[]).map(key=><button key={key} role="tab" aria-selected={tool===key} className={tool===key?'selected':''} onClick={()=>choose(key)} title={tools[key].description}><i className={'monitor-dot '+health[key]}/>{tools[key].name}</button>)}</div>}
  <div className="monitor-toolbar"><span className="monitor-state" role="status"><i className={'monitor-dot '+health[tool]}/>{current.name} · {health[tool]}{checked&&<small>checked {checked}</small>}</span>
   <div className="monitor-screens">{current.screens.map(([label],index)=><button key={label} className={index===screen?'selected':''} onClick={()=>{setScreen(index);setReload(n=>n+1)}}>{label}</button>)}</div>
   <div className="monitor-actions">{!custom&&<a href={url} target="_blank" rel="noreferrer">Open outside <ExternalLink size={13}/></a>}<button onClick={()=>setReload(n=>n+1)}><RefreshCw size={13}/>Reload</button><button onClick={()=>setExpanded(!expanded)}><Maximize2 size={13}/>{expanded?'Exit expanded':'Expand'}</button></div>
  </div>
  {staging&&<p className="monitor-context">Separate preview telemetry. Public listings can be refreshed; automatic applications and email are disabled. No collection worker or scheduler is running.</p>}
  <div ref={frame} className="monitor-frame-wrap">
   {health[tool]!=='up'?<div className="monitor-message">{health[tool]==='checking'?'Checking '+current.name+'…':current.name+' is unavailable, or your session lacks administrator access. This page checks again every 15 seconds.'}</div>:error?<div className="monitor-message error" role="alert">{error}</div>:custom?<PhoenixGraphQLDisplays refreshToken={reload+version}/>:<>
    {!loaded&&<p role="status" className="monitor-loading">Opening {current.name} · {selected[0]}…</p>}
    <iframe key={url+reload+version} src={url} title={current.name+' — '+selected[0]} className="obs-vendor-frame" style={{height}} onLoad={()=>setLoaded(true)} referrerPolicy="no-referrer"/>
   </>}
  </div>
  <p className="muted small">Native monitoring interfaces · administrator access required · read-only controls. A trace does not prove an application was submitted.</p>
 </section>;
}
