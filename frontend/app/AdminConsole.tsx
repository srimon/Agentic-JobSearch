'use client';
/**
 * The administrator console: web traffic, accounts, conversion and machine load on one screen.
 *
 * Every number on this screen comes from /api/admin/overview, which is administrator-only and
 * reads the shared warehouse and Prometheus (src/api/admin_console.py, src/api/admin_queries.py).
 * Nothing is computed from a guess here: each panel shows the source it came from, when that
 * source was last written, the sentence the server wrote to describe it, and a "How this is
 * measured" note per figure. A panel whose source is unavailable, unconfigured or empty says so.
 */
import {useEffect,useMemo,useState} from 'react';
import {Activity,Cpu,Gauge,RefreshCw,TriangleAlert,Users,Wallet} from 'lucide-react';
import './admin-console.css';
import {api,describeError} from './session';

type Row=Record<string,string|number|null>;
type Notes=Record<string,string>;
type Base={panel:string;source:string;generated_at:string;available:boolean;message:string;summary:string;measured:string;notes:Notes;fresh_at?:string|null};
type Traffic=Base&{daily:Row[];by_host:Row[];top_pages:Row[];referrers:Row[];countries:Row[];status:Row[];slowest:Row[];retention_days?:number;
 totals?:{hits:number;bot_hits:number;server_errors:number;days_with_traffic:number;visitors_peak_day:number}};
type Accounts=Base&{daily:Row[];mfa:Row[];signins:Row[];events:Row[];totals?:Row;
 totals_summary?:{new_accounts:number;accounts:number;active_accounts:number;verified_share:number|null;mfa_share:number|null;signins_allowed:number;signins_refused:number}};
type Cost={recorded:boolean;message:string;evidence:{source:string;records:string;to_measure:string}[]};
type Money=Base&{funnel?:{step:string;value:number;of_previous:number|null}[];reach:Row[];spread:Row[];enquiries:Row[];enquiry_pages:Row[];
 repeat_rate?:number|null;enquiry_total?:number;visitor_caveat?:string;ai_cost?:Cost};
type Service={job:string;cpu_cores:number|null;memory_mb:number|null;open_files:number|null;up:boolean};
type Gpu={available:boolean;enabled:boolean;message:string;summary?:string;daily:Row[];gpu_name?:string;samples?:number;
 avg_utilisation?:number;peak_utilisation?:number;avg_memory_mb?:number;peak_memory_mb?:number;total_memory_mb?:number;memory_share?:number|null;last_sample_at?:string};
type Machine=Base&{services:{available:boolean;message:string;services:Service[];samples:{at:number|null;value:number|null}[];targets?:number;targets_up?:number;total_cpu_cores?:number;total_memory_mb?:number};
 gpu:Gpu;host:{available:boolean;message:string};storage:{available:boolean;message:string}};
type Overview={range_days:number;ranges:number[];generated_at:string;cache_seconds:number;
 panels:{traffic:Traffic;accounts:Accounts;monetization:Money;machine:Machine}};

const RANGE_LABEL:Record<number,string>={7:'Last 7 days',30:'Last 30 days',90:'Last 90 days'};
const num=(value:unknown,digits=0)=>typeof value==='number'&&Number.isFinite(value)?value.toLocaleString(undefined,{maximumFractionDigits:digits}):typeof value==='string'&&value!==''?value:'—';
const pct=(value:number|null|undefined)=>typeof value==='number'&&Number.isFinite(value)?(value*100).toFixed(value<0.1?1:0)+'%':'—';
const when=(value:unknown)=>{if(typeof value!=='string'||!value)return 'unknown';const parsed=new Date(value.includes('T')?value:value.replace(' ','T')+'Z');return Number.isNaN(parsed.getTime())?value:parsed.toLocaleString()};
const n=(row:Row,key:string)=>{const value=row[key];return typeof value==='number'?value:Number(value)||0};
const s=(row:Row,key:string)=>{const value=row[key];return value===null||value===undefined?'':String(value)};

/** A line chart drawn as plain SVG: no chart library, and legible where the panel is 400px wide.
 *  A single day is drawn as a flat line across the width rather than a spike out of nowhere. */
function Trend({title,points,unit=''}:{title:string;points:{label:string;value:number}[];unit?:string}){
 if(!points.length)return <p className="ac-empty">No days with data in this range.</p>;
 const max=Math.max(1,...points.map(p=>p.value));
 const single=points.length===1;
 const x=(i:number)=>single?20+i*740:20+(i/(points.length-1))*740;
 const y=(v:number)=>124-(v/max)*96;
 const flat=single?[x(0)+','+y(points[0].value),'760,'+y(points[0].value)].join(' '):'';
 const line=single?flat:points.map((p,i)=>x(i)+','+y(p.value)).join(' ');
 const area='20,124 '+line+' 760,124';
 const first=points[0],last=points[points.length-1];
 return <figure className="ac-trend">
  <svg viewBox="0 0 780 150" role="img" preserveAspectRatio="none"
   aria-label={title+': '+points.length+(points.length===1?' day':' days')+' from '+first.label+' to '+last.label+', highest '+num(max)+unit}>
   <polygon points={area} className="ac-area"/>
   <polyline points={line} className="ac-line" vectorEffect="non-scaling-stroke"/>
   <line x1="20" y1="124" x2="760" y2="124" className="ac-axis" vectorEffect="non-scaling-stroke"/>
   {points.map((p,i)=><circle key={p.label+i} cx={x(i)} cy={y(p.value)} r="4" className="ac-dot"><title>{p.label+': '+p.value+unit}</title></circle>)}
  </svg>
  <figcaption><span>{first.label}</span><span className="ac-peak">peak {num(max)}{unit}</span><span>{single?'':last.label}</span></figcaption>
 </figure>;
}

/** A ranked list drawn as bars, so the shape is readable without reading every number. */
function Bars({rows,label,value,suffix='',empty='Nothing recorded in this range.'}:{rows:Row[];label:(row:Row)=>string;value:(row:Row)=>number;suffix?:string;empty?:string}){
 if(!rows.length)return <p className="ac-empty">{empty}</p>;
 const max=Math.max(1,...rows.map(value));
 return <ul className="ac-bars">{rows.map((row,index)=>{
  const amount=value(row);
  return <li key={label(row)+index}><span className="ac-bar-label" title={label(row)}>{label(row)}</span>
   <span className="ac-bar-track"><span className="ac-bar-fill" style={{width:Math.max(2,(amount/max)*100)+'%'}}/></span>
   <span className="ac-bar-value">{num(amount)}{suffix}</span></li>;
 })}</ul>;
}

function Panel({icon,title,body,children}:{icon:React.ReactNode;title:string;body:Base;children:React.ReactNode}){
 return <section className="ac-panel" aria-labelledby={'ac-'+body.panel}>
  <header><span className="ac-icon" aria-hidden="true">{icon}</span>
   <div><h2 id={'ac-'+body.panel}>{title}</h2>
    <p className="ac-source">Source: {body.source}{body.fresh_at?' · newest record '+when(body.fresh_at):''}</p></div>
  </header>
  <p className={body.available?'ac-summary':'ac-summary ac-warn'} role="status">{body.available?body.summary:body.message}</p>
  {body.available&&children}
  <details className="ac-measured"><summary>How this is measured</summary>
   <p>{body.measured}</p>
   <dl>{Object.entries(body.notes||{}).map(([key,note])=><div key={key}><dt>{key.replaceAll('_',' ')}</dt><dd>{note}</dd></div>)}</dl>
  </details>
 </section>;
}

function TrafficPanel({body}:{body:Traffic}){
 const daily=body.daily||[];
 return <Panel icon={<Activity size={18}/>} title="Web traffic" body={body}>
  <div className="ac-figures">
   <div><strong>{num(body.totals?.hits)}</strong><span>Requests</span></div>
   <div><strong>{num(body.totals?.visitors_peak_day)}</strong><span>Busiest day, visitors</span></div>
   <div><strong>{num(body.totals?.bot_hits)}</strong><span>Bot requests</span></div>
   <div className={body.totals?.server_errors?'ac-bad':''}><strong>{num(body.totals?.server_errors)}</strong><span>Server errors</span></div>
  </div>
  <Trend title="Requests per day" points={daily.map(row=>({label:s(row,'day'),value:n(row,'hits')}))}/>
  <Trend title="Visitors per day" points={daily.map(row=>({label:s(row,'day'),value:n(row,'visitors')}))}/>
  <div className="ac-split">
   <div><h3>By product</h3><Bars rows={body.by_host||[]} label={row=>s(row,'host')} value={row=>n(row,'hits')}/></div>
   <div><h3>Response classes</h3><Bars rows={body.status||[]} label={row=>s(row,'status_class')} value={row=>n(row,'hits')}/></div>
   <div><h3>Countries</h3><Bars rows={body.countries||[]} label={row=>s(row,'country')} value={row=>n(row,'hits')}/></div>
   <div><h3>Referring sites</h3><Bars rows={body.referrers||[]} label={row=>s(row,'referer_host')} value={row=>n(row,'hits')} empty="No request in this range carried a Referer header."/></div>
  </div>
  <h3>Most requested pages</h3>
  <div className="ac-table"><table><thead><tr><th>Product</th><th>Path</th><th>Requests</th><th>Visitors</th></tr></thead>
   <tbody>{(body.top_pages||[]).map((row,index)=><tr key={s(row,'host')+s(row,'path')+index}><td>{s(row,'host')}</td><td><code>{s(row,'path')}</code></td><td>{num(n(row,'hits'))}</td><td>{num(n(row,'visitors'))}</td></tr>)}</tbody></table>
   {!(body.top_pages||[]).length&&<p className="ac-empty">No successful page request in this range.</p>}</div>
  <h3>Slowest paths</h3>
  <div className="ac-table"><table><thead><tr><th>Product</th><th>Path group</th><th>Requests</th><th>95th percentile</th><th>Average</th></tr></thead>
   <tbody>{(body.slowest||[]).map((row,index)=><tr key={s(row,'host')+s(row,'path_group')+index}><td>{s(row,'host')}</td><td><code>{s(row,'path_group')}</code></td><td>{num(n(row,'hits'))}</td><td>{num(n(row,'p95_ms'))} ms</td><td>{num(n(row,'avg_ms'))} ms</td></tr>)}</tbody></table>
   {!(body.slowest||[]).length&&<p className="ac-empty">No path group had at least five requests in this range.</p>}</div>
  <p className="ac-note">Requests are kept for {body.retention_days??90} days, so a 90-day range is everything there is.</p>
 </Panel>;
}

function AccountsPanel({body}:{body:Accounts}){
 const totals=body.totals_summary;
 const outcomes=useMemo(()=>{
  const grouped=new Map<string,number>();
  (body.signins||[]).forEach(row=>grouped.set(s(row,'outcome'),(grouped.get(s(row,'outcome'))||0)+n(row,'events')));
  return [...grouped].map(([outcome,events])=>({outcome,events} as unknown as Row)).sort((a,b)=>n(b,'events')-n(a,'events'));
 },[body.signins]);
 return <Panel icon={<Users size={18}/>} title="Accounts" body={body}>
  <div className="ac-figures">
   <div><strong>{num(totals?.accounts)}</strong><span>Accounts</span></div>
   <div><strong>{num(totals?.new_accounts)}</strong><span>Created in range</span></div>
   <div><strong>{num(totals?.active_accounts)}</strong><span>Enabled</span></div>
   <div><strong>{pct(totals?.verified_share)}</strong><span>Verified</span></div>
   <div><strong>{pct(totals?.mfa_share)}</strong><span>Two-step</span></div>
  </div>
  <Trend title="Accounts created per day" points={(body.daily||[]).map(row=>({label:s(row,'day'),value:n(row,'accounts')}))}/>
  <div className="ac-figures ac-figures-plain">
   <div><strong>{num(n((body.totals||{}) as Row,'active_1d'))}</strong><span>Signed in, 1 day</span></div>
   <div><strong>{num(n((body.totals||{}) as Row,'active_7d'))}</strong><span>Signed in, 7 days</span></div>
   <div><strong>{num(n((body.totals||{}) as Row,'active_30d'))}</strong><span>Signed in, 30 days</span></div>
   <div><strong>{num(n((body.totals||{}) as Row,'unverified_after_a_day'))}</strong><span>Unverified over a day</span></div>
  </div>
  <div className="ac-split">
   <div><h3>Sign-in outcomes</h3><Bars rows={outcomes} label={row=>s(row,'outcome')} value={row=>n(row,'events')} empty="No sign-in was attempted in this range."/></div>
   <div><h3>Two-step by role</h3><Bars rows={body.mfa||[]} label={row=>s(row,'role')+' ('+num(n(row,'active_accounts'))+')'} value={row=>n(row,'with_mfa')} empty="No enabled account to report on."/></div>
  </div>
  <h3>Recorded account events</h3>
  <div className="ac-table"><table><thead><tr><th>Action</th><th>Outcome</th><th>Events</th><th>Accounts</th></tr></thead>
   <tbody>{(body.events||[]).map((row,index)=><tr key={s(row,'action')+s(row,'outcome')+index}><td>{s(row,'action')}</td><td>{s(row,'outcome')}</td><td>{num(n(row,'events'))}</td><td>{num(n(row,'accounts'))}</td></tr>)}</tbody></table>
   {!(body.events||[]).length&&<p className="ac-empty">No account event in this range.</p>}</div>
 </Panel>;
}

function MonetizationPanel({body}:{body:Money}){
 const funnel=body.funnel||[];
 const widest=Math.max(1,...funnel.map(step=>step.value));
 const cost=body.ai_cost;
 return <Panel icon={<Wallet size={18}/>} title="Conversion and usage" body={body}>
  <h3>Visitors to signed-in accounts</h3>
  <ol className="ac-funnel">{funnel.map(step=><li key={step.step}>
   <span className="ac-bar-label">{step.step}</span>
   <span className="ac-bar-track"><span className="ac-bar-fill" style={{width:Math.max(2,(step.value/widest)*100)+'%'}}/></span>
   <span className="ac-bar-value">{num(step.value)}{step.of_previous===null?'':' · '+pct(step.of_previous)+' of the step above'}</span>
  </li>)}</ol>
  {body.visitor_caveat&&<p className="ac-note">{body.visitor_caveat}</p>}
  <div className="ac-figures ac-figures-plain">
   <div><strong>{pct(body.repeat_rate)}</strong><span>Visitors who came back</span></div>
   <div><strong>{num(body.enquiry_total)}</strong><span>Enquiries in range</span></div>
  </div>
  <div className="ac-split">
   <div><h3>Reach per product</h3><Bars rows={body.reach||[]} label={row=>s(row,'host')} value={row=>n(row,'visitors')} empty="No visitor was recorded in this range."/></div>
   <div><h3>Products per visitor</h3><Bars rows={body.spread||[]} label={row=>n(row,'products')===1?'one product':n(row,'products')+' products'} value={row=>n(row,'visitors')} empty="No visitor was recorded in this range."/></div>
   <div><h3>Enquiries per day</h3><Bars rows={body.enquiries||[]} label={row=>s(row,'day')} value={row=>n(row,'enquiries')} empty="No enquiry arrived in this range."/></div>
   <div><h3>Enquiries by page</h3><Bars rows={body.enquiry_pages||[]} label={row=>s(row,'page')} value={row=>n(row,'enquiries')} empty="No enquiry arrived in this range."/></div>
  </div>
  <h3>AI cost</h3>
  <p className="ac-summary ac-warn" role="status">{cost?.message||'Per-call model cost is not recorded.'}</p>
  <div className="ac-table"><table><thead><tr><th>Where a call passes</th><th>What is recorded today</th><th>What would make cost measurable</th></tr></thead>
   <tbody>{(cost?.evidence||[]).map(item=><tr key={item.source}><td>{item.source}</td><td>{item.records}</td><td>{item.to_measure}</td></tr>)}</tbody></table></div>
 </Panel>;
}

function MachinePanel({body}:{body:Machine}){
 const services=body.services;
 const gpu=body.gpu;
 const samples=(services.samples||[]).filter(point=>typeof point.value==='number');
 return <Panel icon={<Cpu size={18}/>} title="Machine" body={body}>
  {services.available?<>
   <div className="ac-figures">
    <div><strong>{services.targets_up}/{services.targets}</strong><span>Metric targets up</span></div>
    <div><strong>{num(services.total_cpu_cores,3)}</strong><span>CPU cores in use</span></div>
    <div><strong>{num(services.total_memory_mb,1)} MB</strong><span>Resident memory</span></div>
   </div>
   <Trend title="Service CPU cores, last hour" unit=" cores"
    points={samples.map((point,index)=>({label:point.at?new Date(point.at*1000).toLocaleTimeString([],{hour:'2-digit',minute:'2-digit'}):String(index),value:Number(point.value)}))}/>
   <div className="ac-table"><table><thead><tr><th>Service</th><th>State</th><th>CPU cores</th><th>Memory</th><th>Open files</th></tr></thead>
    <tbody>{services.services.map(service=><tr key={service.job}><td>{service.job}</td>
     <td><span className={service.up?'ac-pill ac-pill-ok':'ac-pill ac-pill-bad'}>{service.up?'up':'down'}</span></td>
     <td>{num(service.cpu_cores,3)}</td><td>{num(service.memory_mb,1)} MB</td><td>{num(service.open_files)}</td></tr>)}</tbody></table></div>
  </>:<p className="ac-summary ac-warn" role="status">{services.message}</p>}
  <h3>Whole machine</h3>
  <p className="ac-note">{body.host.message}</p>
  <p className="ac-note">{body.storage.message}</p>
  <h3>GPU</h3>
  {gpu.enabled?<>
   <div className="ac-figures">
    <div><strong>{num(gpu.avg_utilisation,1)}%</strong><span>Average use</span></div>
    <div><strong>{num(gpu.peak_utilisation)}%</strong><span>Peak use</span></div>
    <div><strong>{num(gpu.avg_memory_mb)} MB</strong><span>Average memory of {num(gpu.total_memory_mb)} MB</span></div>
    <div><strong>{num(gpu.samples)}</strong><span>Samples</span></div>
   </div>
   <Trend title="GPU use per day" unit="%" points={(gpu.daily||[]).map(row=>({label:s(row,'day'),value:n(row,'avg_utilisation')}))}/>
   <p className="ac-note">{gpu.gpu_name} · newest sample {when(gpu.last_sample_at)}.</p>
  </>:<p className="ac-summary ac-warn" role="status"><Gauge size={15} aria-hidden="true"/> {gpu.message}</p>}
 </Panel>;
}

export default function AdminConsole({version}:{version:number}){
 const [days,setDays]=useState(7),[data,setData]=useState<Overview|null>(null),[loading,setLoading]=useState(true),[error,setError]=useState(''),[refresh,setRefresh]=useState(0);
 useEffect(()=>{
  let active=true;setLoading(true);setError('');
  api<Overview>('/admin/overview?days='+days)
   .then(result=>{if(active)setData(result)})
   .catch(reason=>{if(active)setError(describeError(reason,{403:'Administrator access is required.'}))})
   .finally(()=>{if(active)setLoading(false)});
  return()=>{active=false};
 },[days,refresh,version]);
 const panels=data?.panels;
 return <div className="admin-console">
  <div className="ac-toolbar">
   <div><span className="eyebrow">ADMINISTRATOR CONSOLE</span>
    <p>Web traffic, accounts, conversion and machine load for every Bagala product, from the shared warehouse and the cluster&rsquo;s own metrics.</p></div>
   <label>Date range<select aria-label="Date range" value={days} onChange={event=>setDays(Number(event.target.value))}>
    {(data?.ranges||[7,30,90]).map(value=><option key={value} value={value}>{RANGE_LABEL[value]||value+' days'}</option>)}</select></label>
   <button className="secondary" disabled={loading} onClick={()=>setRefresh(value=>value+1)}><RefreshCw size={15} className={loading?'spin':''}/>Refresh</button>
  </div>
  {error&&<div className="message error" role="alert"><TriangleAlert size={16}/> {error}</div>}
  {loading&&!panels?<div className="ac-loading" role="status"><RefreshCw className="spin"/> Reading the warehouse and the cluster metrics…</div>:
   panels?<>
    <TrafficPanel body={panels.traffic}/>
    <AccountsPanel body={panels.accounts}/>
    <MonetizationPanel body={panels.monetization}/>
    <MachinePanel body={panels.machine}/>
    <p className="ac-note">Built {when(data?.generated_at)}. Each panel is held for {data?.cache_seconds??45} seconds, so a refresh does not query the warehouse again straight away.</p>
   </>:null}
 </div>;
}
