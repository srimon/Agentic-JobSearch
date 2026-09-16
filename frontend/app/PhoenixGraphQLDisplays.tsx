'use client';
import {useEffect,useMemo,useState} from 'react';
import {Activity,Clock3,Database,RefreshCw,TriangleAlert} from 'lucide-react';
import {apiFetch} from './session';

type Point={timestamp:string;okCount?:number|null;errorCount?:number|null;unsetCount?:number|null;totalCount?:number|null;p50?:number|null;p95?:number|null;max?:number|null};
type Span={spanId:string;name:string;statusCode:string;startTime:string;latencyMs:number|null};
type Display={project:string;hours:number;generated_at:string;summary:{traces:number;spans:number;latency_p50_ms:number|null;latency_p95_ms:number|null};span_counts:Point[];trace_status:Point[];latency:Point[];recent_operations:Span[]};

const number=(value:number|null|undefined,digits=0)=>value==null?'Unavailable':value.toLocaleString(undefined,{maximumFractionDigits:digits});
const time=(value:string)=>new Date(value).toLocaleString();

function Lines({title,description,data,series}:{title:string;description:string;data:Point[];series:{key:keyof Point,label:string,color:string}[]}){
 const usable=data.filter(point=>series.some(item=>typeof point[item.key]==='number'));
 const max=Math.max(1,...usable.flatMap(point=>series.map(item=>typeof point[item.key]==='number'?Number(point[item.key]):0)));
 const coords=(key:keyof Point)=>usable.map((point,index)=>`${24+(index/Math.max(1,usable.length-1))*752},${164-(Number(point[key]??0)/max)*132}`).join(' ');
 return <article className="graphql-chart"><h3>{title}</h3><p>{description}</p>{usable.length?<><div className="graphql-legend">{series.map(item=><span key={item.label}><i style={{background:item.color}}/>{item.label}</span>)}</div><svg viewBox="0 0 800 205" role="img" aria-label={title}><line x1="24" y1="164" x2="776" y2="164"/><text x="24" y="18">{number(max,1)}</text>{series.map(item=><polyline key={item.label} points={coords(item.key)} fill="none" stroke={item.color} strokeWidth="3" vectorEffect="non-scaling-stroke"/>)}<text x="24" y="194">{new Date(usable[0].timestamp).toLocaleString()}</text><text x="610" y="194">{new Date(usable.at(-1)!.timestamp).toLocaleString()}</text></svg></>:<div className="graphql-empty">No samples in this time range.</div>}</article>
}

export default function PhoenixGraphQLDisplays({refreshToken}:{refreshToken:number}){
 const [hours,setHours]=useState(24),[data,setData]=useState<Display|null>(null),[loading,setLoading]=useState(true),[error,setError]=useState(''),[refresh,setRefresh]=useState(0);
 useEffect(()=>{let cancelled=false;const controller=new AbortController();setLoading(true);setError('');
  const timer=setTimeout(()=>controller.abort(),30000);
  apiFetch('/phoenix-graphql/displays?hours='+hours,{cache:'no-store',signal:controller.signal}).then(async response=>{if(!response.ok)throw Error(response.status===401?'Your session has expired.':response.status===403?'Operator access is required.':'Phoenix GraphQL display is unavailable.');return response.json()}).then(result=>{if(!cancelled)setData(result)}).catch(reason=>{if(!cancelled)setError(reason.name==='AbortError'?'Phoenix GraphQL timed out.':reason.message)}).finally(()=>{clearTimeout(timer);if(!cancelled)setLoading(false)});
  return()=>{cancelled=true;clearTimeout(timer);controller.abort()};
 },[hours,refresh,refreshToken]);
 const failures=useMemo(()=>data?.trace_status.reduce((sum,point)=>sum+(point.errorCount??0),0)??0,[data]);
 return <div className="graphql-displays">
  <div className="graphql-toolbar"><div><span className="eyebrow">PHOENIX GRAPHQL</span><h3>Agent execution overview</h3><p>Live aggregate and operation metadata from the isolated <code>jobsearch</code> project.</p></div><label>Time range<select value={hours} onChange={event=>setHours(Number(event.target.value))}><option value={24}>Past 24 hours</option><option value={168}>Past 7 days</option></select></label><button className="secondary" disabled={loading} onClick={()=>setRefresh(value=>value+1)}><RefreshCw size={15} className={loading?'spin':''}/>Refresh data</button></div>
  {error&&<div className="message error" role="alert"><TriangleAlert size={18}/>{error}</div>}
  {loading&&!data?<div className="graphql-loading"><RefreshCw className="spin"/>Running Phoenix GraphQL queries…</div>:data?<>
   <div className="graphql-stats"><article><Activity/><strong>{number(data.summary.traces)}</strong><span>Traces</span></article><article><Database/><strong>{number(data.summary.spans)}</strong><span>Spans</span></article><article><Clock3/><strong>{number(data.summary.latency_p50_ms,1)} ms</strong><span>Median latency</span></article><article><Clock3/><strong>{number(data.summary.latency_p95_ms,1)} ms</strong><span>P95 latency</span></article><article className={failures?'warning':''}><TriangleAlert/><strong>{number(failures)}</strong><span>Error traces</span></article></div>
   <div className="graphql-grid"><Lines title="Span volume" description="Root and child spans per time bin." data={data.span_counts} series={[{key:'totalCount',label:'Total spans',color:'#0f766e'}]}/><Lines title="Trace outcomes" description="Phoenix trace status over time." data={data.trace_status} series={[{key:'okCount',label:'OK',color:'#16a34a'},{key:'errorCount',label:'Error',color:'#dc2626'}]}/><Lines title="Trace latency" description="Median and p95 execution time in milliseconds." data={data.latency} series={[{key:'p50',label:'P50',color:'#2563eb'},{key:'p95',label:'P95',color:'#9333ea'}]}/></div>
   <article className="graphql-table"><div><h3>Recent root operations</h3><p>Latest ten operations by start time. Inputs, outputs and attributes are excluded.</p></div>{data.recent_operations.length?<div className="table-scroll"><table><thead><tr><th>Operation</th><th>Status</th><th>Started</th><th>Latency</th><th>Span ID</th></tr></thead><tbody>{data.recent_operations.map(span=><tr key={span.spanId}><td>{span.name}</td><td><span className={'graphql-status '+span.statusCode.toLowerCase()}>{span.statusCode}</span></td><td>{time(span.startTime)}</td><td>{number(span.latencyMs,1)} ms</td><td><code>{span.spanId}</code></td></tr>)}</tbody></table></div>:<div className="graphql-empty">No operations in this time range.</div>}</article>
   <p className="muted small">Updated {time(data.generated_at)}. Counts and latency describe telemetry records; they do not prove a job application was submitted.</p>
  </>:null}
 </div>
}
