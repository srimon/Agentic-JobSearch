'use client';
/**
 * The administrator console: web traffic, accounts, conversion and machine load for every Bagala
 * product on one screen, as charts.
 *
 * Three rules this screen keeps:
 *
 * 1. every panel leads with a graph. The sentence the server wrote sits under the charts, not above
 *    them, and the numbers keep tabular figures so a column of them lines up;
 * 2. every traffic and conversion chart can be read for all products together or for one product.
 *    The default view draws one line per product, so the split is visible without touching anything;
 * 3. nothing here flatters the products. Bot requests are left out of every visit and visitor figure
 *    (and can be drawn as their own series), a sign-up means a self-service account rather than one
 *    of the console and seed accounts the acceptance script leaves behind, and the funnel starts at
 *    the product hosts rather than at the welcome site. What is not measurable at all - per-call AI
 *    cost, whole-machine CPU and memory, GPU while sampling is off - is a calm empty state inside
 *    the chart with the reason and what would turn it on, never a blank box and never a guess.
 *
 * Every number comes from /api/admin/overview, which is administrator-only and reads the shared
 * warehouse and Prometheus (src/api/admin_console.py, src/api/admin_queries.py). The screen refetches
 * all of it every two hours by itself, pausing while the tab is hidden; the Refresh button is still
 * there for anyone who does not want to wait. Chart geometry lives in admin-charts.mjs, which is
 * tested on its own (frontend/tests/admin-charts.test.mjs).
 */
import {useCallback, useEffect, useMemo, useRef, useState} from 'react';
import {Activity, Cpu, Gauge, Info, RefreshCw, TriangleAlert, Users, Wallet} from 'lucide-react';
import './admin-console.css';
import {api, describeError} from './session';
import {barRows, CHART_BOX, funnelBars, labelIndexes, shapeSeries, sparkline, stackSegments} from './admin-charts.mjs';

type Row=Record<string,string|number|null>;
type Notes=Record<string,string>;
type Series={key:string;label:string;values:number[];tone?:number;dashed?:boolean};
type Product={host:string;name:string;kind:string};
type Base={panel:string;source:string;generated_at:string;available:boolean;message:string;summary:string;measured:string;notes:Notes;fresh_at?:string|null};
type Traffic=Base&{daily:Row[];daily_by_host:Row[];daily_visitors:Row[];by_host:Row[];top_pages:Row[];referrers:Row[];referrers_by_host:Row[];
 countries:Row[];countries_by_host:Row[];status:Row[];status_by_host:Row[];slowest:Row[];retention_days?:number;bot_note?:string;
 visitor_caveat?:string;product_note?:string;
 totals?:{human_hits:number;all_hits:number;bot_hits:number;server_errors:number;days_with_traffic:number;visitors_peak_day:number;product_visitors_peak_day:number}};
type AccountTotals={accounts:number;new_accounts:number;active_accounts:number;disabled_accounts:number;verified:number;with_mfa:number;
 verified_share:number|null;mfa_share:number|null;unverified_after_a_day:number;signed_in_in_range:number;ever_signed_in:number;
 internal_accounts:number;internal_active:number;all_accounts:number;all_new_accounts:number;signins_allowed:number;signins_refused:number};
type Accounts=Base&{daily:Row[];self_daily:Row[];mfa:Row[];signins:Row[];events:Row[];counting_rule?:string;totals_summary?:AccountTotals};
type Cost={recorded:boolean;message:string;evidence:{source:string;records:string;to_measure:string}[]};
type Money=Base&{funnel?:{step:string;value:number;of_previous:number|null}[];reach:Row[];spread:Row[];enquiries:Row[];enquiry_pages:Row[];
 repeat_rate?:number|null;enquiry_total?:number;visitor_caveat?:string;bot_note?:string;funnel_note?:string;ai_cost?:Cost;
 comparison?:{all_visitors:number;all_new_accounts:number;all_signed_in:number};attribution?:{signups:string;enquiries:string}};
type Service={job:string;cpu_cores:number|null;memory_mb:number|null;open_files:number|null;up:boolean};
type Gpu={available:boolean;enabled:boolean;message:string;summary?:string;daily:Row[];gpu_name?:string;samples?:number;
 avg_utilisation?:number;peak_utilisation?:number;avg_memory_mb?:number;peak_memory_mb?:number;total_memory_mb?:number;memory_share?:number|null;last_sample_at?:string};
type Machine=Base&{services:{available:boolean;message:string;services:Service[];samples:{at:number|null;value:number|null}[];targets?:number;targets_up?:number;total_cpu_cores?:number;total_memory_mb?:number};
 gpu:Gpu;host:{available:boolean;message:string};storage:{available:boolean;message:string}};
type Overview={range_days:number;ranges:number[];generated_at:string;cache_seconds:number;refresh_minutes?:number;
 products?:Product[];data_quality?:string[];panels:{traffic:Traffic;accounts:Accounts;monetization:Money;machine:Machine}};

/** How often the screen refetches every panel by itself. Said on screen, so nobody has to guess. */
const REFRESH_MINUTES=120;
const RANGE_LABEL:Record<number,string>={7:'Last 7 days',30:'Last 30 days',90:'Last 90 days'};
const ALL='all';

const num=(value:unknown,digits=0)=>typeof value==='number'&&Number.isFinite(value)?value.toLocaleString(undefined,{maximumFractionDigits:digits}):typeof value==='string'&&value!==''?value:'—';
const pct=(value:number|null|undefined)=>typeof value==='number'&&Number.isFinite(value)?(value*100).toFixed(value<0.1&&value>0?1:0)+'%':'—';
const when=(value:unknown)=>{if(typeof value!=='string'||!value)return 'unknown';const parsed=new Date(value.includes('T')?value:value.replace(' ','T')+'Z');return Number.isNaN(parsed.getTime())?value:parsed.toLocaleString()};
const clock=(at:number|null)=>at===null?'—':new Date(at).toLocaleTimeString([],{hour:'2-digit',minute:'2-digit'});
const n=(row:Row,key:string)=>{const value=row[key];return typeof value==='number'?value:Number(value)||0};
const s=(row:Row,key:string)=>{const value=row[key];return value===null||value===undefined?'':String(value)};
const day=(value:string)=>/^\d{4}-\d{2}-\d{2}/.test(value)?value.slice(5):value;

/** A calm empty state where a chart would be: the reason, and what would fill it. Never a blank box. */
function NoChart({children}:{children:React.ReactNode}){
 return <div className="ac-nochart" role="status"><Info size={15} aria-hidden="true"/><p>{children}</p></div>;
}

/**
 * A line chart drawn as plain SVG. It carries its own axis, gridlines and a readout that doubles as
 * the legend: a swatch, a name and the exact value under the pointer or the keyboard cursor (the
 * last day until something is hovered or the arrow keys move it). For anyone who cannot see it, the
 * svg has a one-sentence label and the same numbers follow as a table only a screen reader reads.
 */
function Chart({title,series,labels,unit='',integer=true,empty='No day in this range has anything to show.'}:
 {title:string;series:Series[];labels:string[];unit?:string;integer?:boolean;empty?:React.ReactNode}){
 const [active,setActive]=useState<number|null>(null);
 const shape=useMemo(()=>shapeSeries(series,CHART_BOX,{integer}),[series,integer]);
 const move=useCallback((step:number)=>setActive(current=>{
  const last=shape.length-1;
  if(last<0)return null;
  const from=current===null?last:current;
  return Math.min(last,Math.max(0,step===0?last:from+step));
 }),[shape.length]);
 if(!shape.length||!series.some(item=>item.values.length))return <NoChart>{empty}</NoChart>;
 const index=active===null?shape.length-1:Math.min(active,shape.length-1);
 const marks=labelIndexes(shape.length,4);
 const step=shape.length>1?shape.plotWidth/(shape.length-1):shape.plotWidth;
 const peak=Math.max(...series.map(item=>Math.max(0,...item.values)));
 const label=title+': '+shape.length+(shape.length===1?' day':' days')+' from '+labels[0]+' to '+labels[shape.length-1]
  +', '+series.map(item=>item.label.toLowerCase()+' highest '+num(Math.max(0,...item.values))+unit).join(', ')+'.';
 return <figure className="ac-chart">
  <p className="ac-readout" aria-live="polite"><span className="ac-readout-day">{labels[index]}</span>
   {series.map(item=><span key={item.key} className="ac-readout-item">
    <span className={'ac-swatch ac-tone'+(item.tone||1)+(item.dashed?' ac-swatch-dashed':'')} aria-hidden="true"/>
    {item.label} <strong className="ac-num">{num(item.values[index]??0)}{unit}</strong></span>)}</p>
  <svg viewBox={'0 0 '+CHART_BOX.width+' '+CHART_BOX.height} className="ac-svg" role="img" tabIndex={0} aria-label={label}
   onMouseLeave={()=>setActive(null)} onBlur={()=>setActive(null)}
   onKeyDown={event=>{
    const keys:Record<string,number>={ArrowLeft:-1,ArrowRight:1,Home:-shape.length,End:shape.length};
    if(keys[event.key]===undefined)return;
    event.preventDefault();move(keys[event.key]);
   }}>
   {shape.ticks.map(tick=><g key={tick}>
    <line x1={CHART_BOX.left} x2={CHART_BOX.width-CHART_BOX.right} y1={shape.y(tick)} y2={shape.y(tick)} className="ac-grid"/>
    <text x={CHART_BOX.left-8} y={shape.y(tick)+4} className="ac-axis-label" textAnchor="end">{num(tick,1)}</text>
   </g>)}
   {shape.series.length===1&&<path d={shape.series[0].area} className={'ac-area ac-tone'+(shape.series[0].tone||1)}/>}
   {shape.series.map(item=><path key={item.key} d={item.line} vectorEffect="non-scaling-stroke"
    className={'ac-line ac-tone'+(item.tone||1)+(item.dashed?' ac-line-dashed':'')}/>)}
   <line x1={CHART_BOX.left} x2={CHART_BOX.width-CHART_BOX.right} y1={shape.baseline} y2={shape.baseline} className="ac-axis"/>
   {marks.map(mark=><text key={mark} x={shape.x(mark)} y={CHART_BOX.height-11} className="ac-axis-label"
    textAnchor={mark===0?'start':mark===shape.length-1?'end':'middle'}>{labels[mark]}</text>)}
   <line x1={shape.x(index)} x2={shape.x(index)} y1={CHART_BOX.top} y2={shape.baseline} className="ac-cursor"/>
   {shape.series.map(item=>item.points[index]?<circle key={item.key} cx={shape.x(index)} cy={item.points[index].y} r="4"
    className={'ac-dot ac-tone'+(item.tone||1)}/>:null)}
   {shape.series[0].points.map(point=><rect key={point.index} className="ac-hit"
    x={Math.max(0,shape.x(point.index)-step/2)} y={0} width={Math.max(step,6)} height={CHART_BOX.height}
    onMouseEnter={()=>setActive(point.index)}/>)}
  </svg>
  <table className="ac-sr"><caption>{title}{peak?'':' (nothing above zero in this range)'}</caption>
   <thead><tr><th scope="col">Day</th>{series.map(item=><th key={item.key} scope="col">{item.label}</th>)}</tr></thead>
   <tbody>{labels.map((name,position)=><tr key={name+position}><th scope="row">{name}</th>
    {series.map(item=><td key={item.key}>{num(item.values[position]??0)}{unit}</td>)}</tr>)}</tbody></table>
 </figure>;
}

/** A ranked comparison drawn as bars, so the shape is readable without reading every number. */
function Bars({rows,empty='Nothing recorded in this range.',highlight}:
 {rows:{key:string;label:string;value:number;text?:string;muted?:boolean}[];empty?:React.ReactNode;highlight?:string}){
 if(!rows.length)return <NoChart>{empty}</NoChart>;
 return <ul className="ac-bars">{barRows(rows).map(row=>
  <li key={row.key} className={highlight&&row.key===highlight?'ac-bar-on':undefined}>
   <span className="ac-bar-label" title={row.label}>{row.label}</span>
   <span className="ac-bar-track"><span className={'ac-bar-fill'+(row.muted?' ac-bar-muted':'')} style={{width:row.width+'%'}}/></span>
   <span className="ac-bar-value ac-num">{row.text??num(row.value)}</span></li>)}</ul>;
}

/** A status mix as one stacked bar: every class in proportion, with its share beside it. */
function Stack({parts,empty='Nothing recorded in this range.'}:{parts:{key:string;label:string;value:number}[];empty?:React.ReactNode}){
 const {total,segments}=stackSegments(parts);
 if(!total)return <NoChart>{empty}</NoChart>;
 return <div className="ac-stackwrap">
  <div className="ac-stack" role="img" aria-label={segments.map(part=>part.label+' '+pct(part.share)).join(', ')}>
   {segments.filter(part=>part.width>0).map((part,order)=><span key={part.key} className={'ac-stack-part ac-tone'+((order%6)+1)}
    style={{width:part.width+'%'}}><span className="ac-sr">{part.label} {pct(part.share)}</span></span>)}</div>
  <ul className="ac-legend">{segments.filter(part=>part.value>0).map((part,order)=><li key={part.key}>
   <span className={'ac-swatch ac-tone'+((order%6)+1)} aria-hidden="true"/>{part.label}
   <strong className="ac-num">{num(part.value)}</strong><span className="ac-num">{pct(part.share)}</span></li>)}</ul>
 </div>;
}

/** The funnel: a step per row with the share of the step above it printed between the two. */
function Funnel({steps,marks}:{steps:{step:string;value:number;of_previous:number|null}[];marks?:Record<string,string>}){
 if(!steps.length)return <NoChart>No funnel can be drawn without a visitor count.</NoChart>;
 return <ol className="ac-funnel">{funnelBars(steps).map(step=><li key={step.step}>
  {step.of_previous===null?null:<span className="ac-funnel-gap ac-num" aria-hidden="true">↓ {pct(step.of_previous)}</span>}
  <span className="ac-funnel-row">
   <span className="ac-bar-label">{step.step}{marks?.[step.step]?<em className="ac-mark">{marks[step.step]}</em>:null}</span>
   <span className="ac-bar-track"><span className="ac-bar-fill" style={{width:step.width+'%'}}/></span>
   <span className="ac-bar-value ac-num">{num(step.value)}{step.of_previous===null?'':' · '+pct(step.of_previous)+' of the step above'}</span>
  </span></li>)}</ol>;
}

/** A small line and the value it ends on, for a measurement that is only interesting as a shape. */
function Spark({values,label,unit='',current,empty}:{values:number[];label:string;unit?:string;current?:number|null;empty?:React.ReactNode}){
 const line=sparkline(values,{width:220,height:46});
 if(!line.path)return <NoChart>{empty||'No sample was recorded.'}</NoChart>;
 const now=current===undefined?line.current:current;
 return <div className="ac-spark">
  <svg viewBox="0 0 220 46" role="img" aria-label={label+': '+values.length+' samples, now '+num(now,3)+unit+', highest '+num(line.top,3)+unit}>
   <path d={line.path} className="ac-line ac-tone1" vectorEffect="non-scaling-stroke"/></svg>
  <p><strong className="ac-num">{num(now,3)}{unit}</strong><span>now · highest {num(line.top,3)}{unit}</span></p>
 </div>;
}

function Card({title,note,children,wide}:{title:string;note?:React.ReactNode;children:React.ReactNode;wide?:boolean}){
 return <article className={wide?'ac-card ac-card-wide':'ac-card'}>
  <h3>{title}</h3>{children}{note?<p className="ac-caption">{note}</p>:null}</article>;
}

function Panel({icon,title,body,children}:{icon:React.ReactNode;title:string;body:Base;children:React.ReactNode}){
 return <section className="ac-panel" aria-labelledby={'ac-'+body.panel}>
  <header><span className="ac-icon" aria-hidden="true">{icon}</span>
   <div><h2 id={'ac-'+body.panel}>{title}</h2>
    <p className="ac-source">Source: {body.source}{body.fresh_at?' · newest record '+when(body.fresh_at):''}</p></div>
  </header>
  {body.available?<><div className="ac-cards">{children}</div>
   <p className="ac-summary" role="status">{body.summary}</p></>
   :<p className="ac-summary ac-warn" role="status">{body.message}</p>}
  <details className="ac-measured"><summary>How this is measured</summary>
   <p>{body.measured}</p>
   <dl>{Object.entries(body.notes||{}).map(([key,note])=><div key={key}><dt>{key.replaceAll('_',' ')}</dt><dd>{note}</dd></div>)}</dl>
  </details>
 </section>;
}

// ----- per-product shaping ----------------------------------------------------------------------

const toneFor=(host:string,products:Product[])=>{const found=products.findIndex(item=>item.host===host);return (found<0?products.length:found)%6+1};
const nameFor=(host:string,products:Product[])=>products.find(item=>item.host===host)?.name||host;

/** One value per day for one host, with the days a host saw nothing filled in as zero. */
function hostSeries(rows:Row[],days:string[],host:string,field:string){
 const found=new Map<string,number>();
 rows.forEach(row=>{if(s(row,'host')===host)found.set(s(row,'day'),n(row,field))});
 return days.map(name=>found.get(name)??0);
}

function daySeries(rows:Row[],days:string[],field:string){
 const found=new Map<string,number>();
 rows.forEach(row=>found.set(s(row,'day'),n(row,field)));
 return days.map(name=>found.get(name)??0);
}

// ----- panels ------------------------------------------------------------------------------------

function TrafficPanel({body,product,products,bots}:{body:Traffic;product:string;products:Product[];bots:boolean}){
 const totals=body.totals;
 const hosts=useMemo(()=>{
  const seen=(body.by_host||[]).map(row=>s(row,'host'));
  return [...products.map(item=>item.host).filter(host=>seen.includes(host)),...seen.filter(host=>!products.some(item=>item.host===host))];
 },[body.by_host,products]);
 const days=useMemo(()=>[...new Set((body.daily||[]).map(row=>s(row,'day')))].sort(),[body.daily]);
 const labels=useMemo(()=>days.map(day),[days]);
 const one=product!==ALL;
 const requests=useMemo(()=>{
  const rows=body.daily_by_host||[];
  const chosen:Series[]=one
   ?[{key:product,label:nameFor(product,products),values:hostSeries(rows,days,product,'human_hits'),tone:toneFor(product,products)}]
   :hosts.map(host=>({key:host,label:nameFor(host,products),values:hostSeries(rows,days,host,'human_hits'),tone:toneFor(host,products)}));
  if(!bots)return chosen;
  const botValues=one?hostSeries(rows,days,product,'bot_hits'):daySeries(body.daily||[],days,'bot_hits');
  return [...chosen,{key:'bots',label:'Bots',values:botValues,tone:5,dashed:true}];
 },[body.daily,body.daily_by_host,bots,days,hosts,one,product,products]);
 const visitors=useMemo(()=>one
  ?[{key:product,label:nameFor(product,products),values:hostSeries(body.daily_by_host||[],days,product,'human_visitors'),tone:toneFor(product,products)}]
  :[{key:'all',label:'All hosts',values:daySeries(body.daily_visitors||[],days,'human_visitors'),tone:1},
    {key:'products',label:'Product hosts only',values:daySeries(body.daily_visitors||[],days,'product_visitors'),tone:2}],
 [body.daily_by_host,body.daily_visitors,days,one,product,products]);
 const perHost=useMemo(()=>(body.by_host||[]).map(row=>({key:s(row,'host'),label:nameFor(s(row,'host'),products),
  value:bots?n(row,'hits'):n(row,'hits')-n(row,'bot_hits'),
  text:num(bots?n(row,'hits'):n(row,'hits')-n(row,'bot_hits'))+(bots?' with bots':'')}))
  .sort((left,right)=>right.value-left.value),[body.by_host,bots,products]);
 const status=useMemo(()=>{
  const rows=one?(body.status_by_host||[]).filter(row=>s(row,'host')===product):body.status||[];
  const grouped=new Map<string,number>();
  rows.forEach(row=>grouped.set(s(row,'status_class'),(grouped.get(s(row,'status_class'))||0)+n(row,'hits')));
  return [...grouped].sort((left,right)=>left[0].localeCompare(right[0])).map(([label,value])=>({key:label,label,value}));
 },[body.status,body.status_by_host,one,product]);
 const countries=useMemo(()=>{
  const rows=one?(body.countries_by_host||[]).filter(row=>s(row,'host')===product):body.countries||[];
  return rows.slice(0,10).map(row=>({key:s(row,'country')+s(row,'host'),label:s(row,'country'),value:n(row,'hits')}));
 },[body.countries,body.countries_by_host,one,product]);
 const referrers=useMemo(()=>{
  const rows=one?(body.referrers_by_host||[]).filter(row=>s(row,'host')===product):body.referrers||[];
  return rows.slice(0,10).map(row=>({key:s(row,'referer_host')+s(row,'host'),label:s(row,'referer_host'),value:n(row,'hits')}));
 },[body.referrers,body.referrers_by_host,one,product]);
 const pages=useMemo(()=>(body.top_pages||[]).filter(row=>!one||s(row,'host')===product).slice(0,10)
  .map(row=>({key:s(row,'host')+s(row,'path'),label:(one?'':nameFor(s(row,'host'),products)+' ')+s(row,'path'),
   value:n(row,'hits'),text:num(n(row,'hits'))+' · '+num(n(row,'visitors'))+' visitors'})),[body.top_pages,one,product,products]);
 const slowest=useMemo(()=>(body.slowest||[]).filter(row=>!one||s(row,'host')===product).slice(0,10)
  .map(row=>({key:s(row,'host')+s(row,'path_group'),label:(one?'':nameFor(s(row,'host'),products)+' ')+s(row,'path_group'),
   value:n(row,'p95_ms'),text:num(n(row,'p95_ms'))+' ms · avg '+num(n(row,'avg_ms'))+' ms'})),[body.slowest,one,product,products]);
 const scope=one?nameFor(product,products):'every product';
 return <Panel icon={<Activity size={18}/>} title="Web traffic" body={body}>
  <Card title={'Requests per day · '+scope}
   note={<>Requests from people, one line per product. {bots?'The dashed line is bot traffic.':'Bots are excluded; turn on “Show bots” to draw them.'}</>}>
   <Chart title="Requests per day" series={requests} labels={labels}/></Card>
  <Card title={'Visitors per day · '+scope}
   note={<>{one?'Distinct non-bot visitors of this host.':'The gap between the two lines is the welcome site: someone reading the front page is not using a product.'} {body.visitor_caveat}</>}>
   <Chart title="Visitors per day" series={visitors} labels={labels}/></Card>
  <Card title="Requests per product" note="Every host side by side for the whole range. Selecting one above filters the charts, not this comparison.">
   <Bars rows={perHost} highlight={one?product:undefined}/></Card>
  <Card title={'Response classes · '+scope} note="Every request in the range, bots included, by what the edge answered.">
   <Stack parts={status}/></Card>
  <Card title={'Where requests come from · '+scope} note="The country Cloudflare reported, non-bot requests only.">
   <Bars rows={countries} empty="No non-bot request in this range carried a country."/></Card>
  <Card title={'Referring sites · '+scope} note="The host part of the Referer header; requests without one are left out.">
   <Bars rows={referrers} empty="No request in this range carried a Referer header."/></Card>
  <Card title={'Most requested pages · '+scope} note="Successful non-bot page requests. The path never carries a query string.">
   <Bars rows={pages} empty="No successful page request in this range."/></Card>
  <Card title={'Slowest paths · '+scope} note="Edge-measured 95th percentile per first path segment, for groups with at least five requests.">
   <Bars rows={slowest} empty="No path group had at least five requests in this range."/></Card>
  <Card title="Range in figures" wide
   note={<>Requests are kept for {body.retention_days??90} days, so a 90-day range is everything there is. {body.bot_note}</>}>
   <div className="ac-figures">
    <div><strong className="ac-num">{num(totals?.human_hits)}</strong><span>Requests from people</span></div>
    <div><strong className="ac-num">{num(totals?.visitors_peak_day)}</strong><span>Busiest day, visitors</span></div>
    <div><strong className="ac-num">{num(totals?.product_visitors_peak_day)}</strong><span>Busiest day, product visitors</span></div>
    <div><strong className="ac-num">{num(totals?.bot_hits)}</strong><span>Bot requests, excluded above</span></div>
    <div className={totals?.server_errors?'ac-bad':''}><strong className="ac-num">{num(totals?.server_errors)}</strong><span>Server errors</span></div>
   </div></Card>
 </Panel>;
}

function AccountsPanel({body}:{body:Accounts}){
 const totals=body.totals_summary;
 const days=useMemo(()=>[...new Set([...(body.daily||[]),...(body.self_daily||[])].map(row=>s(row,'day')))].sort(),[body.daily,body.self_daily]);
 const labels=useMemo(()=>days.map(day),[days]);
 const signups=useMemo(()=>[
  {key:'self',label:'Sign-ups',values:daySeries(body.self_daily||[],days,'accounts'),tone:1},
  {key:'all',label:'All accounts created, console and seed included',values:daySeries(body.daily||[],days,'accounts'),tone:5,dashed:true},
 ],[body.daily,body.self_daily,days]);
 const signins=useMemo(()=>{
  const outcomes=[...new Set((body.signins||[]).map(row=>s(row,'outcome')))].sort();
  return outcomes.map((outcome,order)=>({key:outcome,label:outcome,tone:order%6+1,
   values:daySeries((body.signins||[]).filter(row=>s(row,'outcome')===outcome),days,'events')}));
 },[body.signins,days]);
 const outcomes=useMemo(()=>{
  const grouped=new Map<string,number>();
  (body.signins||[]).forEach(row=>grouped.set(s(row,'outcome'),(grouped.get(s(row,'outcome'))||0)+n(row,'events')));
  return [...grouped].sort((left,right)=>right[1]-left[1]).map(([label,value])=>({key:label,label,value}));
 },[body.signins]);
 const enabled=[
  {key:'enabled',label:'Enabled',value:totals?.active_accounts||0},
  {key:'disabled',label:'Disabled',value:totals?.disabled_accounts||0},
 ];
 const verified=[
  {key:'verified',label:'Verified',value:totals?.verified||0},
  {key:'unverified',label:'Not verified',value:Math.max(0,(totals?.accounts||0)-(totals?.verified||0))},
 ];
 return <Panel icon={<Users size={18}/>} title="Accounts" body={body}>
  <Card title="Sign-ups per day" note="A sign-up is a self-service account. The dashed line is every account created, console and seed accounts included, and is only there for comparison.">
   <Chart title="Sign-ups per day" series={signups} labels={labels} empty="No account was created in this range."/></Card>
  <Card title="Sign-in attempts per day" note="Recorded sign-in attempts by outcome, every account included.">
   <Chart title="Sign-in attempts per day" series={signins} labels={labels} empty="No sign-in was attempted in this range."/></Card>
  <Card title="Sign-ups by state" note={<>Both bars cover the same {num(totals?.accounts)} sign-ups; {num(totals?.with_mfa)} of them use two-step. Console and seed accounts are not in either.</>}>
   <p className="ac-substack">Enabled or disabled</p>
   <Stack parts={enabled} empty="No self-service account exists yet."/>
   <p className="ac-substack">Verified address</p>
   <Stack parts={verified} empty="No self-service account exists yet."/></Card>
  <Card title="Sign-in outcomes" note="Every sign-in attempt in the range, grouped by what happened.">
   <Bars rows={outcomes} empty="No sign-in was attempted in this range."/></Card>
  <Card title="Two-step by role" note="Every enabled account, console and seed accounts included: this one is not a sign-up figure.">
   <Bars rows={(body.mfa||[]).map(row=>({key:s(row,'role'),label:s(row,'role')+' ('+num(n(row,'active_accounts'))+')',value:n(row,'with_mfa')}))}
    empty="No enabled account to report on."/></Card>
  <Card title="Range in figures" note={body.counting_rule}>
   <div className="ac-figures">
    <div><strong className="ac-num">{num(totals?.accounts)}</strong><span>Sign-ups, all time</span></div>
    <div><strong className="ac-num">{num(totals?.new_accounts)}</strong><span>Sign-ups in range</span></div>
    <div><strong className="ac-num">{pct(totals?.verified_share)}</strong><span>Verified</span></div>
    <div><strong className="ac-num">{pct(totals?.mfa_share)}</strong><span>Two-step</span></div>
    <div><strong className="ac-num">{num(totals?.signed_in_in_range)}</strong><span>Signed in, in range</span></div>
    <div className="ac-figure-aside"><strong className="ac-num">{num(totals?.internal_accounts)}</strong><span>Console and seed accounts, not sign-ups</span></div>
   </div></Card>
  <Card title="Recorded account events" wide note="Every recorded account event in the range, every account included.">
   <div className="ac-table"><table><thead><tr><th>Action</th><th>Outcome</th><th>Events</th><th>Accounts</th></tr></thead>
    <tbody>{(body.events||[]).map((row,index)=><tr key={s(row,'action')+s(row,'outcome')+index}><td>{s(row,'action')}</td><td>{s(row,'outcome')}</td>
     <td className="ac-num">{num(n(row,'events'))}</td><td className="ac-num">{num(n(row,'accounts'))}</td></tr>)}</tbody></table>
    {!(body.events||[]).length&&<NoChart>No account event in this range.</NoChart>}</div></Card>
 </Panel>;
}

function MonetizationPanel({body,product,products}:{body:Money;product:string;products:Product[]}){
 const one=product!==ALL;
 const cost=body.ai_cost;
 const reach=useMemo(()=>(body.reach||[]).map(row=>({key:s(row,'host'),label:nameFor(s(row,'host'),products),value:n(row,'visitors')})),[body.reach,products]);
 const funnel=useMemo(()=>{
  const steps=body.funnel||[];
  if(!one||!steps.length)return steps;
  const here=(body.reach||[]).find(row=>s(row,'host')===product);
  const visitors=here?n(here,'visitors'):0;
  const rest=steps.slice(1);
  return [{step:'Product visitors',value:visitors,of_previous:null},
   ...rest.map((step,order)=>({...step,of_previous:order===0?(visitors?step.value/visitors:null):step.of_previous}))];
 },[body.funnel,body.reach,one,product]);
 const marks=one?{'Sign-ups':'all products','Verified':'all products','Signed in':'all products'}:undefined;
 const days=useMemo(()=>[...new Set((body.enquiries||[]).map(row=>s(row,'day')))].sort(),[body.enquiries]);
 const enquiries=useMemo(()=>[{key:'enquiries',label:'Enquiries',values:daySeries(body.enquiries||[],days,'enquiries'),tone:1}],[body.enquiries,days]);
 return <Panel icon={<Wallet size={18}/>} title="Conversion and usage" body={body}>
  <Card title={'From a visit to a signed-in account · '+(one?nameFor(product,products):'every product')}
   note={<>{body.funnel_note} {one?'Only the first step can be read per product: an account is not tied to one.':''}</>}>
   <Funnel steps={funnel} marks={marks}/></Card>
  <Card title="Visitors per product" note={<>Distinct non-bot visitors per host. Someone who used two products is counted in both rows, so these do not add up to the total. {body.visitor_caveat}</>}>
   <Bars rows={reach} highlight={one?product:undefined} empty="No visitor was recorded in this range."/></Card>
  <Card title="Products per visitor" note="How many different hosts each visitor touched. This one is about the crossover, so it is always every product together.">
   <Bars rows={(body.spread||[]).map(row=>({key:s(row,'products'),label:n(row,'products')===1?'one host':n(row,'products')+' hosts',value:n(row,'visitors')}))}
    empty="No visitor was recorded in this range."/></Card>
  <Card title="Enquiries per day" note={body.attribution?.enquiries}>
   {one?<NoChart>{body.attribution?.enquiries}</NoChart>
    :<Chart title="Enquiries per day" series={enquiries} labels={days.map(day)} empty="No enquiry arrived in this range."/>}</Card>
  <Card title="Range in figures" note={<>{body.attribution?.signups} {body.bot_note}</>}>
   <div className="ac-figures">
    <div><strong className="ac-num">{pct(body.repeat_rate)}</strong><span>Visitors who came back</span></div>
    <div><strong className="ac-num">{num(body.enquiry_total)}</strong><span>Enquiries in range</span></div>
    <div className="ac-figure-aside"><strong className="ac-num">{num(body.comparison?.all_visitors)}</strong><span>Visitors of every host, welcome site included</span></div>
    <div className="ac-figure-aside"><strong className="ac-num">{num(body.comparison?.all_new_accounts)}</strong><span>All accounts created, console and seed included</span></div>
   </div></Card>
  <Card title="AI cost" wide note="Nothing is estimated here: the console shows what each place records instead of a price.">
   <NoChart>{cost?.message||'Per-call model cost is not recorded.'}</NoChart>
   <div className="ac-table"><table><thead><tr><th>Where a call passes</th><th>What is recorded today</th><th>What would make cost measurable</th></tr></thead>
    <tbody>{(cost?.evidence||[]).map(item=><tr key={item.source}><td>{item.source}</td><td>{item.records}</td><td>{item.to_measure}</td></tr>)}</tbody></table></div></Card>
 </Panel>;
}

function MachinePanel({body}:{body:Machine}){
 const services=body.services;
 const gpu=body.gpu;
 const samples=(services.samples||[]).filter(point=>typeof point.value==='number').map(point=>Number(point.value));
 const cpu=(services.services||[]).map(service=>({key:service.job,label:service.job,value:service.cpu_cores||0,
  text:num(service.cpu_cores,3)+' cores'})).sort((left,right)=>right.value-left.value);
 const memory=(services.services||[]).map(service=>({key:service.job,label:service.job,value:service.memory_mb||0,
  text:num(service.memory_mb,1)+' MB'})).sort((left,right)=>right.value-left.value);
 const gpuDaily=(gpu.daily||[]).map(row=>n(row,'avg_utilisation'));
 return <Panel icon={<Cpu size={18}/>} title="Machine" body={body}>
  <Card title="Service CPU, last hour" note={services.available?'Every scraped service together, one sample a minute.':undefined}>
   {services.available?<Spark values={samples} label="Service CPU cores over the last hour" unit=" cores"
    empty="Prometheus answered, but it has no range for this expression yet."/>:<NoChart>{services.message}</NoChart>}</Card>
  <Card title="CPU per service" note={services.available?services.targets_up+' of '+services.targets+' scrape targets are up.':undefined}>
   {services.available?<Bars rows={cpu} empty="No service reported CPU."/>:<NoChart>{services.message}</NoChart>}</Card>
  <Card title="Memory per service" note={services.available?'Resident set of each process, as Prometheus last scraped it.':undefined}>
   {services.available?<Bars rows={memory} empty="No service reported memory."/>:<NoChart>{services.message}</NoChart>}</Card>
  <Card title="GPU" note={gpu.enabled?gpu.gpu_name+' · newest sample '+when(gpu.last_sample_at):undefined}>
   {gpu.enabled?<>
    <Spark values={gpuDaily} label="GPU use per day" unit="%" current={gpu.avg_utilisation??null}/>
    <div className="ac-figures ac-figures-plain">
     <div><strong className="ac-num">{num(gpu.peak_utilisation)}%</strong><span>Peak use</span></div>
     <div><strong className="ac-num">{num(gpu.avg_memory_mb)} MB</strong><span>Average of {num(gpu.total_memory_mb)} MB</span></div>
     <div><strong className="ac-num">{num(gpu.samples)}</strong><span>Samples</span></div>
    </div></>:<NoChart><Gauge size={15} aria-hidden="true"/> {gpu.message}</NoChart>}</Card>
  <Card title="Whole machine" wide note="Nothing on this cluster collects these, so nothing is shown rather than a figure that would be a guess.">
   <NoChart>{body.host.message}</NoChart><NoChart>{body.storage.message}</NoChart></Card>
  {services.available?<Card title="Services" wide note="Each scraped service as Prometheus last saw it.">
   <div className="ac-table"><table><thead><tr><th>Service</th><th>State</th><th>CPU cores</th><th>Memory</th><th>Open files</th></tr></thead>
    <tbody>{services.services.map(service=><tr key={service.job}><td>{service.job}</td>
     <td><span className={service.up?'ac-pill ac-pill-ok':'ac-pill ac-pill-bad'}>{service.up?'up':'down'}</span></td>
     <td className="ac-num">{num(service.cpu_cores,3)}</td><td className="ac-num">{num(service.memory_mb,1)} MB</td>
     <td className="ac-num">{num(service.open_files)}</td></tr>)}</tbody></table></div></Card>:null}
 </Panel>;
}

/** The strip along the top: one card per product, and the card is how a product is chosen. */
function Strip({traffic,money,accounts,products,product,onChoose,bots}:
 {traffic:Traffic;money:Money;accounts:Accounts;products:Product[];product:string;onChoose:(host:string)=>void;bots:boolean}){
 const hosts=useMemo(()=>{
  const seen=(traffic.by_host||[]).map(row=>s(row,'host'));
  return [...products.filter(item=>seen.includes(item.host)),
   ...seen.filter(host=>!products.some(item=>item.host===host)).map(host=>({host,name:host,kind:'product'}))];
 },[traffic.by_host,products]);
 const visits=(host:string)=>{
  const row=(traffic.by_host||[]).find(item=>s(item,'host')===host);
  return row?(bots?n(row,'hits'):n(row,'hits')-n(row,'bot_hits')):0;
 };
 const visitors=(host:string)=>{
  const row=(money.reach||[]).find(item=>s(item,'host')===host);
  return row?n(row,'visitors'):0;
 };
 const cards=[{host:ALL,name:'All products',kind:'all'},...hosts];
 return <><div className="ac-strip" role="group" aria-label="Choose a product">
  {cards.map(item=><button key={item.host} type="button" aria-pressed={product===item.host}
   className={'ac-strip-card'+(product===item.host?' ac-strip-on':'')+(item.kind==='site'?' ac-strip-site':'')}
   onClick={()=>onChoose(item.host)}>
   <span className="ac-strip-name">{item.name}</span>
   <span className="ac-strip-host">{item.host===ALL?'every host below':item.host}</span>
   <span className="ac-strip-rows">
    <span><i>Visits</i><b className="ac-num">{num(item.host===ALL?traffic.totals?.[bots?'all_hits':'human_hits']:visits(item.host))}</b></span>
    <span><i>Visitors</i><b className="ac-num">{item.host===ALL?num(money.comparison?.all_visitors):num(visitors(item.host))}</b></span>
    <span><i>Sign-ups</i><b className="ac-num" title={item.host===ALL?undefined:money.attribution?.signups}>
     {item.host===ALL?num(accounts.totals_summary?.new_accounts):'—'}</b></span>
    <span><i>Enquiries</i><b className="ac-num" title={item.host===ALL?undefined:money.attribution?.enquiries}>
     {item.host===ALL?num(money.enquiry_total):'—'}</b></span>
   </span></button>)}
 </div>
 <p className="ac-note">Choose a card to read every traffic and conversion chart for that host; “All products” draws one line per product.
  Visits and visitors are {bots?'shown with bots included':'counted without bots'} for the range above. A dash means the figure cannot be
  split per product: {money.attribution?.signups} {money.attribution?.enquiries}</p></>;
}

export default function AdminConsole({version}:{version:number}){
 const [days,setDays]=useState(7),[data,setData]=useState<Overview|null>(null),[loading,setLoading]=useState(true);
 const [error,setError]=useState(''),[refresh,setRefresh]=useState(0);
 const [product,setProduct]=useState(ALL),[bots,setBots]=useState(false),[loadedAt,setLoadedAt]=useState<number|null>(null);
 const loaded=useRef<number|null>(null);
 useEffect(()=>{
  let active=true;setLoading(true);setError('');
  api<Overview>('/admin/overview?days='+days)
   .then(result=>{if(active){setData(result);const at=Date.now();loaded.current=at;setLoadedAt(at)}})
   .catch(reason=>{if(active)setError(describeError(reason,{403:'Administrator access is required.'}))})
   .finally(()=>{if(active)setLoading(false)});
  return()=>{active=false};
 },[days,refresh,version]);
 const minutes=data?.refresh_minutes||REFRESH_MINUTES;
 // Refetch on its own every two hours. A hidden tab does not refetch - nobody is reading it, and the
 // warehouse should not be queried for a background tab - and a tab that comes back after its turn
 // has passed refetches straight away. Both are cleaned up when the console is left.
 useEffect(()=>{
  const period=minutes*60*1000;
  const due=()=>loaded.current===null||Date.now()-loaded.current>=period;
  const tick=()=>{if(!document.hidden)setRefresh(value=>value+1)};
  const back=()=>{if(!document.hidden&&due())setRefresh(value=>value+1)};
  const timer=setInterval(tick,period);
  document.addEventListener('visibilitychange',back);
  return()=>{clearInterval(timer);document.removeEventListener('visibilitychange',back)};
 },[minutes]);
 const panels=data?.panels;
 const products=data?.products||[];
 const cadence=minutes%60?minutes+' minutes':minutes===60?'hour':minutes/60+' hours';
 return <div className="admin-console">
  <div className="ac-toolbar">
   <div><span className="eyebrow">ADMINISTRATOR CONSOLE</span>
    <p>Traffic, accounts, conversion and machine load for every Bagala product, as charts, from the shared warehouse and the cluster&rsquo;s own metrics.</p></div>
   <label>Date range<select aria-label="Date range" value={days} onChange={event=>setDays(Number(event.target.value))}>
    {(data?.ranges||[7,30,90]).map(value=><option key={value} value={value}>{RANGE_LABEL[value]||value+' days'}</option>)}</select></label>
   <label className="ac-check"><input type="checkbox" checked={bots} onChange={event=>setBots(event.target.checked)}/>Show bots</label>
   <div className="ac-refresh">
    <button className="secondary" disabled={loading} onClick={()=>setRefresh(value=>value+1)}><RefreshCw size={15} className={loading?'spin':''}/>Refresh</button>
    <p className="ac-num">Updated {clock(loadedAt)}, next update {clock(loadedAt===null?null:loadedAt+minutes*60*1000)} · every {cadence}</p>
   </div>
  </div>
  {error&&<div className="message error" role="alert"><TriangleAlert size={16}/> {error}</div>}
  {panels?<>
   <section className="ac-quality" aria-label="What these numbers leave out">
    <h2><Info size={16} aria-hidden="true"/> What these numbers leave out</h2>
    <ul>{(data?.data_quality||[]).map(line=><li key={line.slice(0,24)}>{line}</li>)}</ul>
   </section>
   {panels.traffic.available&&panels.monetization.available&&panels.accounts.available?
    <Strip traffic={panels.traffic} money={panels.monetization} accounts={panels.accounts} products={products}
     product={product} onChoose={setProduct} bots={bots}/>:null}
   <TrafficPanel body={panels.traffic} product={product} products={products} bots={bots}/>
   <MonetizationPanel body={panels.monetization} product={product} products={products}/>
   <AccountsPanel body={panels.accounts}/>
   <MachinePanel body={panels.machine}/>
   <p className="ac-note">Built {when(data?.generated_at)}. Each panel is held for {data?.cache_seconds??45} seconds on the server, which is far
    shorter than the {cadence} between refreshes, so every refresh - scheduled or by hand - reads the warehouse again.</p>
  </>:loading?<div className="ac-loading" role="status"><RefreshCw className="spin"/> Reading the warehouse and the cluster metrics…</div>:null}
 </div>;
}
