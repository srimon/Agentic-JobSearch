'use client';

import {useEffect,useState,useRef} from 'react';
import MotionScene from './MotionScene';
import Observability from './Observability';
import DataQuality from './DataQuality';
import DataModel from './DataModel';
import Governance from './Governance';
import DataManagement,{DataNavigation} from './DataManagement';
import {dataGroups} from './data-management';
import SearchOverview from './SearchOverview';
import Learning from './Learning';
import CollectionStatus from './CollectionStatus';
import JobBoards from './JobBoards';
import Intake from './Intake';
import ApplicationCheck,{Applications} from './ApplicationCheck';

import {CircleCheck,TriangleAlert,Clock3,LockKeyhole,Mail,Archive,Search,Bookmark,ArrowUpRight,MapPin,BriefcaseBusiness,ShieldCheck,Activity,Database,ChevronLeft,ChevronRight,RefreshCw,X,SlidersHorizontal,LogOut} from 'lucide-react';



type User={name:string;roles:string[]};

type Job={learning?:{adjustment:number;reasons:string[];version:number;enabled:boolean};next_action?:string|null;archived_at?:string|null;final_status?:string|null;last_emailed_at?:string|null;dismissal_reason?:string|null;first_seen_at?:string;application_status?:string|null;id:string;title:string;company:string;location:string;work_mode:string;level:string;match_status:string;reason:string;posted_at:string|null;last_seen_at:string;url:string;saved:boolean;stage:string|null;description?:string;country_status:string;evidence?:{provider?:string;company_url?:string}};

type Source={id:number;company:string;provider:string;board:string;enabled:boolean;last_success_at:string|null;last_error:string|null;latest_status:string|null;fetched:number|null;matched:number|null};

type Run={id:string;company:string;status:string;created_at:string;fetched:number;matched:number;error:string|null};

type Session={user:User|null;identity_ready:boolean};

const dismissalLabels:Record<string,string>={spam:'Spam',fake_posting:'Suspected fake posting',not_relevant:'Not relevant',dismissed:'Dismissed',old_posting:'Old posting',already_applied_elsewhere:'Already applied elsewhere',not_interested:'Not interested',no_longer_available:'No longer available'};
const applied=(job:Job)=>job.application_status==='submitted'||['applied','interviewing','offer','closed'].includes(job.stage||'');
const submissionBlocked=(job:Job)=>!!job.archived_at||!!job.dismissal_reason||applied(job)||['submitting','submission_unknown'].includes(job.application_status||'');
const dateText=(value:string|null)=>value?new Date(value).toLocaleDateString(undefined,{month:'short',day:'numeric',year:'numeric'}):'Posting date unknown';

async function api<T>(path:string,init?:RequestInit):Promise<T>{const res=await fetch('/api'+path,{...init,cache:'no-store',headers:{'Content-Type':'application/json',...init?.headers}});if(!res.ok){const data=await res.json().catch(()=>({}));throw new Error(data.detail||'Unable to load data. Please try again.')}return res.json()}



export default function Home(){

 const [session,setSession]=useState<Session|null>(null),[error,setError]=useState(''),[loading,setLoading]=useState(false);

 const [tab,setTab]=useState('matches'),[q,setQ]=useState(''),[query,setQuery]=useState(''),[date,setDate]=useState('24h'),[level,setLevel]=useState(''),[mode,setMode]=useState(''),[page,setPage]=useState(1);

 const [sort,setSort]=useState('recommended'),[feedback,setFeedback]=useState<Record<string,string>>({});
 const changing=useRef(false);
 const [busyJob,setBusyJob]=useState<string|null>(null),[lockedIds,setLockedIds]=useState<string[]>([]);
 function finalizeLocal(id:string){setLockedIds(ids=>[...ids,id]);setItems(rows=>rows.filter(j=>j.id!==id));setDetail(null);window.location.replace('/?view=emailed&archived='+encodeURIComponent(id))}
 const [showDismissed,setShowDismissed]=useState(false),[dismissTarget,setDismissTarget]=useState<Job|null>(null),[dismissReason,setDismissReason]=useState('old_posting'),[dismissBusy,setDismissBusy]=useState(false);
 const [items,setItems]=useState<Job[]>([]),[total,setTotal]=useState(0),[sources,setSources]=useState<Source[]>([]),[runs,setRuns]=useState<Run[]>([]),[detail,setDetail]=useState<Job|null>(null),[version,setVersion]=useState(0);

 const [company,setCompany]=useState(''),[provider,setProvider]=useState('ashby'),[board,setBoard]=useState(''),[notice,setNotice]=useState('');

 const [username,setUsername]=useState(''),[password,setPassword]=useState(''),[signingIn,setSigningIn]=useState(false);

 const user=session?.user, operator=!!user?.roles.some(r=>['operator','administrator'].includes(r)),member=!!user?.roles.some(r=>['member','administrator'].includes(r));

 useEffect(()=>{const params=new URLSearchParams(window.location.search);if(['matches','emailed','archive','saved','observability','quality','model','governance','runs',...dataGroups.flatMap(g=>g.tools.map(t=>'data-'+t.id))].includes(params.get('view')||'')){setTab(params.get('view')!);setDate(params.get('view')==='archive'?'any':'24h');setShowDismissed(params.get('view')==='emailed')}},[]);
 useEffect(()=>{if(!user)return;const id=new URLSearchParams(window.location.search).get('job');if(id&&/^[0-9a-f-]{36}$/i.test(id))api<Job>('/jobs/'+id).then(j=>{if(j.archived_at)setNotice('This job is archived and locked.');else setDetail(j)}).catch(e=>setError(e.message));},[user]);

 useEffect(()=>{if(!user)return;const id=new URLSearchParams(window.location.search).get('archived');if(id&&/^[0-9a-f-]{36}$/i.test(id))api<Job>('/jobs/'+id).then(j=>{if(j.archived_at)setNotice('Status saved. The job is archived and permanently locked.')}).catch(e=>setError(e.message));},[user]);
 useEffect(()=>{api<Session>('/session').then(setSession).catch(e=>setError(e.message))},[]);

 useEffect(()=>{const timer=setTimeout(()=>{setQuery(q);setPage(1)},300);return()=>clearTimeout(timer)},[q]);

 useEffect(()=>{if(!user)return;if(tab.startsWith('data-')||['intake','applications','observability','quality','model','governance'].includes(tab)){setLoading(false);return;}let active=true;setLoading(true);setError('');const params=new URLSearchParams({q:query,date,level,mode,page:String(page),sort,view:tab,show_dismissed:String(showDismissed)});

 const task=tab==='sources'?api<Source[]>('/sources').then(x=>{if(active)setSources(x)}):tab==='runs'?api<Run[]>('/runs').then(x=>{if(active)setRuns(x)}):api<{items:Job[];total:number}>('/jobs?'+params).then(x=>{if(active){setItems(x.items);setTotal(x.total)}});

 task.catch(e=>{if(active)setError(e.message)}).finally(()=>{if(active)setLoading(false)});return()=>{active=false};},[user,tab,query,date,level,mode,page,version,showDismissed,sort]);

 function choose(value:string){if(value.startsWith('data-'))window.history.replaceState(null,'','?view='+value);setDate(value==='archive'?'any':'24h');if(['emailed','archive'].includes(value)){setQ('');setQuery('');setLevel('');setMode('')}setShowDismissed(value==='emailed');setTab(value);setPage(1);setDetail(null);setNotice('')}

 async function save(job:Job,stage?:string){try{await api('/jobs/'+job.id+'/saved',{method:'PUT',body:JSON.stringify({saved:stage?true:!job.saved,stage:stage||'saved'})});setVersion(v=>v+1);setNotice(stage?'Application status updated.':job.saved?'Job removed from saved.':'Job saved.')}catch(e){setError((e as Error).message)}}



 async function updateStatus(job:Job,value:string){
  if(!value||changing.current||job.archived_at||lockedIds.includes(job.id))return;
  if(value!=='applied'){
   if(job.last_emailed_at){await dismiss(job,true,value);return}
   setDetail(null);setDismissReason(value);setDismissTarget(job);return;
  }
  changing.current=true;setBusyJob(job.id);
  try{await api('/jobs/'+job.id+'/mark-applied',{method:'POST'});
   if(job.last_emailed_at)finalizeLocal(job.id);else{setVersion(v=>v+1);setDetail(null)}
   setNotice(job.last_emailed_at?'Successfully applied. Archived and permanently locked.':'Successfully applied — confirmed by you.');
  }catch(e){setError((e as Error).message);setVersion(v=>v+1)}finally{changing.current=false;setBusyJob(null)}
 }
 async function dismiss(job:Job,dismissed:boolean,reason=dismissReason){
  if(changing.current||job.archived_at||lockedIds.includes(job.id))return;
  changing.current=true;setBusyJob(job.id);setDismissBusy(true);
  try{await api('/jobs/'+job.id+'/dismissal',{method:'PUT',body:JSON.stringify({dismissed,reason,feedback_reason:reason==='not_relevant'?(feedback[job.id]||null):null})});
   setDismissTarget(null);setDetail(null);
   if(dismissed&&job.last_emailed_at)finalizeLocal(job.id);else setVersion(v=>v+1);
   setNotice(dismissed&&job.last_emailed_at?'Job archived. Status permanently locked.':dismissed?'Job dismissed.':'Job restored.');
  }catch(e){setError((e as Error).message);setVersion(v=>v+1)}finally{changing.current=false;setBusyJob(null);setDismissBusy(false)}
 }
 async function open(job:Job){
  if(changing.current||job.archived_at||lockedIds.includes(job.id))return;
  try{const fresh=await api<Job>('/jobs/'+job.id);
   if(fresh.archived_at){finalizeLocal(job.id);setNotice('This job is archived and locked.');return}
   setDetail({...fresh,next_action:job.next_action});
  }catch(e){setError((e as Error).message)}
 }

 const labels:Record<string,string>={archive:'Archive',emailed:'Emailed jobs',matches:'All opportunities',saved:'Saved jobs',review:'Needs review',sources:'Source coverage',runs:'Collection runs',intake:'Resume & profile',applications:'Application checks',observability:'Observability',quality:'Data quality',model:'Data model',governance:'Data governance',...Object.fromEntries(dataGroups.flatMap(g=>g.tools.map(t=>['data-'+t.id,t.name])))};

 return <div className="shell"><MotionScene loading={loading} saving={!!busyJob} label={labels[tab]}/><aside className="sidebar"><div className="workspace-label">YOUR WORKSPACE</div><nav aria-label="Main navigation">

 {[['matches','Opportunities',BriefcaseBusiness],['saved','Saved jobs',Bookmark],['emailed','Emailed jobs',Mail],['archive','Archive',Archive],...(member?[['intake','Resume & profile',ShieldCheck],['applications','Application checks',BriefcaseBusiness]]:[]),...(operator?[['review','Needs review',ShieldCheck]]:[]),['sources','Sources',Database],...(operator?[['runs','Activity',Activity],['observability','Observability',Activity],]:[])].map(([key,label,Icon])=>{const C=Icon as typeof Search;return <button key={key as string} aria-current={tab===key?'page':undefined} className={tab===key?'nav-item active':'nav-item'} onClick={()=>choose(key as string)}><C size={18}/>{label as string}{key==='matches'&&<span className="nav-dot"/>}</button>})}{operator&&process.env.NEXT_PUBLIC_JOBSEARCH_ENVIRONMENT==='staging'&&<DataNavigation tab={tab} choose={choose}/>}</nav>

 <div className="scope-card"><span className="eyebrow">SEARCH PROFILE</span><h3>Leadership.<br/>Data & AI.</h3><p>Director / Sr Director / VP / SVP · CTO / CIO / CDO / CAIO</p><span className="country"><span/>United States</span></div>

 <div className="identity"><ShieldCheck size={18}/><div><strong>{user?.name||'Private workspace'}</strong><small>Private account</small></div>{user&&<button className="icon-button" title="Sign out" onClick={async()=>{await api('/auth/logout',{method:'POST'});location.reload()}}><LogOut size={16}/></button>}</div></aside>

 <main><header className="topbar app-header"><h2 className="app-title">AI Autonomous Job Search</h2><span className="region">US market</span></header>
 {process.env.NEXT_PUBLIC_JOBSEARCH_ENVIRONMENT==='staging'&&<p className="notice" role="status">Staging · Separate public job feed. No automatic applications or email. The default view shows jobs posted in the past 24 hours; choose Any time to inspect older verified listings.</p>}

 <section className="content"><div key={tab} className="page-heading page-arrival"><div><div className="eyebrow">YOUR NEXT CHAPTER</div><h1>{labels[tab]}</h1><p>{tab==='emailed'?'Work through the jobs in your email reports. Selecting a status saves it immediately, permanently locks the job and moves it to Archive.':tab==='archive'?'Completed decisions are locked. Archived jobs are excluded from future reports.':tab==='sources'?'See where your opportunities come from.':tab==='runs'?'Track source checks and collection outcomes.':tab==='model'?'Explore the PostgreSQL table structure and declared relationships.':tab==='quality'?'Evidence-based checks for the separate staging feed.':tab==='observability'?'Live metrics and traces, together in your workspace.':'Find the role where your experience makes a difference.'}</p></div><button className="secondary" disabled={!user||loading} onClick={()=>setVersion(v=>v+1)}><RefreshCw size={16} className={loading?'spin':''}/>Refresh</button></div>

 {error&&<div className="message error" role="alert">{error}<button onClick={()=>location.reload()}>Reload</button></div>}

 {['matches','emailed'].includes(tab)&&<SearchOverview view={tab}/>}
 {user&&member&&['matches','emailed','saved'].includes(tab)&&<Learning onChange={()=>setVersion(v=>v+1)}/>}
 {user&&!tab.startsWith('data-')&&!['observability','quality','model','governance'].includes(tab)&&<CollectionStatus version={version} date={date}/>}
 {notice&&<div className="message" role="status">{notice}</div>}

 {!session&&!error?<div className="empty">Connecting to your workspace…</div>:!user?<><div className="filters preview-filters"><div className="search"><Search size={19}/><input disabled placeholder="Search title or company" aria-label="Search title or company"/></div><label>Date posted<select disabled defaultValue="Past 24 hours"><option>Any time</option><option>Past 24 hours</option><option>Past 7 days</option><option>Past 30 days</option></select></label></div><div className="signin-card"><div className="lock-icon"><ShieldCheck size={32}/></div><span className="eyebrow">A PRIVATE SEARCH</span><h2>Your next opportunity<br/>starts here.</h2><p>Sign in with your Jobsearch account to browse leadership roles, save opportunities, and follow your search.</p><form className="login-form" onSubmit={async e=>{e.preventDefault();setSigningIn(true);setError('');try{await api('/auth/login',{method:'POST',body:JSON.stringify({username,password})});setPassword('');setSession(await api<Session>('/session'))}catch(e){setError((e as Error).message);setPassword('')}finally{setSigningIn(false)}}}><label>Username<input autoComplete="username" required maxLength={128} value={username} onChange={e=>setUsername(e.target.value)}/></label><label>Password<input type="password" autoComplete="current-password" required maxLength={128} value={password} onChange={e=>setPassword(e.target.value)}/></label><button className="primary" disabled={signingIn}>{signingIn?'Signing in…':'Sign in'}</button><p className="muted small">Accounts are created by your administrator.</p></form><div className="signin-tags"><span>US opportunities</span><span>Source-backed listings</span><span>Private saved jobs</span></div></div></>:

 tab.startsWith('data-')?(operator&&process.env.NEXT_PUBLIC_JOBSEARCH_ENVIRONMENT==='staging'?<DataManagement tab={tab} version={version}/>:<div className="message">Staging operator access is required.</div>):tab==='governance'?(operator?<Governance/>:<div className="message">Operator access is required.</div>):tab==='model'?(operator?<DataModel version={version}/>:<div className="message">Operator access is required.</div>):tab==='quality'?(operator?<DataQuality version={version}/>:<div className="message">Operator access is required.</div>):tab==='observability'?(operator?<Observability version={version}/>:<div className="message">Operator access is required.</div>):tab==='intake'?<Intake/>:tab==='applications'?<Applications version={version}/>:tab==='sources'?<><JobBoards/><div className="table-wrap"><table><thead><tr><th>Company / board</th><th>Provider</th><th>Last successful check</th><th>Latest run</th><th>Candidates</th><th/></tr></thead><tbody>{sources.map(s=><tr key={s.id}><td><strong>{s.company}</strong><small>{s.board}</small></td><td>{s.provider}</td><td>{s.last_success_at?new Date(s.last_success_at).toLocaleString():'Never checked'}</td><td><span className={'badge '+(s.last_error?'warning':'')}>{s.last_error||s.latest_status||'Not started'}</span></td><td>{s.matched??'—'}</td><td>{operator&&<button className="secondary" onClick={async()=>{try{const r=await api<{queued:boolean}>('/sources/'+s.id+'/refresh',{method:'POST'});setNotice(r.queued?'Refresh queued.':'A refresh is already active, or this source cannot be checked again yet.');setVersion(v=>v+1)}catch(e){setError((e as Error).message)}}}>Check source</button>}</td></tr>)}</tbody></table>{!sources.length&&<div className="empty">No sources configured yet.</div>}</div>{operator&&<form className="source-form" onSubmit={async e=>{e.preventDefault();try{await api('/sources',{method:'POST',body:JSON.stringify({company,provider,board})});setCompany('');setBoard('');setVersion(v=>v+1)}catch(e){setError((e as Error).message)}}}><h2>Add an employer board</h2><p className="muted">Use the board identifier from the employer’s official careers page.</p><div className="form-row"><input required value={company} onChange={e=>setCompany(e.target.value)} placeholder="Company name" aria-label="Company name"/><select value={provider} onChange={e=>setProvider(e.target.value)} aria-label="ATS provider"><option value="ashby">Ashby</option><option value="greenhouse">Greenhouse</option><option value="lever">Lever</option></select><input required pattern="[A-Za-z0-9_-]{1,100}" value={board} onChange={e=>setBoard(e.target.value)} placeholder="Board identifier" aria-label="Board identifier"/><button className="primary">Add source</button></div></form>}</>:

 tab==='runs'?<div className="table-wrap"><table><thead><tr><th>Company</th><th>Requested</th><th>Status</th><th>Fetched</th><th>Candidates</th><th>Error</th></tr></thead><tbody>{runs.map(r=><tr key={r.id}><td>{r.company}</td><td>{new Date(r.created_at).toLocaleString()}</td><td><span className="badge">{r.status}</span></td><td>{r.fetched}</td><td>{r.matched}</td><td>{r.error||'—'}</td></tr>)}</tbody></table>{!runs.length&&<div className="empty">No collection runs yet.</div>}</div>:

 <><div className="filters"><label>Order<select aria-label="Job order" value={sort} onChange={e=>{setSort(e.target.value);setPage(1)}}><option value="recommended">Recommended for you</option><option value="newest">Newest first</option></select></label><div className="search"><Search size={19}/><input value={q} onChange={e=>setQ(e.target.value)} placeholder="Search title or company" aria-label="Search title or company"/></div><label>Date posted<select value={date} onChange={e=>{setDate(e.target.value);setPage(1)}}><option value="any">Any time</option><option value="24h">Past 24 hours</option><option value="7d">Past 7 days</option><option value="30d">Past 30 days</option></select></label><label>Leadership level<select value={level} onChange={e=>{setLevel(e.target.value);setPage(1)}}><option value="">All levels</option>{['Director','Senior Director','VP','SVP','C-suite'].map(x=><option key={x}>{x}</option>)}</select></label><label>Workplace<select value={mode} onChange={e=>{setMode(e.target.value);setPage(1)}}><option value="">All workplaces</option>{['Remote','Hybrid','On-site','Unknown'].map(x=><option key={x}>{x}</option>)}</select></label></div>

 <label className="dismissed-filter"><input type="checkbox" checked={showDismissed} onChange={e=>{setShowDismissed(e.target.checked);setPage(1)}}/> Show dismissed</label>
 <div className="result-line"><span><strong>{loading?'…':total.toLocaleString()}</strong> {tab==='review'?'candidates to review':'opportunities'}<span className="muted"> · United States</span></span><span><SlidersHorizontal size={14}/>{sort==='recommended'&&tab!=='archive'?'Feedback ranking · newest breaks ties':tab==='emailed'?'Most recently emailed first':'Newest posted first'}</span></div>

 {date!=='any'&&<p className="filter-note">Based on the source’s posting date. Listings with unknown dates are excluded.</p>}

 <div className={'job-list'+(loading?' results-loading':'')} aria-busy={loading}>{!loading&&!items.length?<div className="empty"><Search size={28}/><h2>{tab==='emailed'?'No emailed jobs to show':'No listings match these filters'}</h2><p>{tab==='emailed'?'Jobs appear here after Gmail accepts a tracked report. Check your filters if a job is missing.':'This view uses the employer’s posting date, not the date we discovered the job. Try a wider date range to see older verified listings.'}</p>{tab==='matches'&&date!=='any'&&<button className="secondary" onClick={()=>{setDate('any');setPage(1)}}>View older verified jobs</button>}<button className="secondary" onClick={()=>choose('sources')}>View sources</button></div>:items.filter(job=>tab==='archive'||!lockedIds.includes(job.id)).map(job=><article inert={busyJob===job.id} className={'job-card'+(job.archived_at?' job-dismissed':job.dismissal_reason?' job-dismissed':applied(job)?' job-applied':'')} key={job.id}><div className="company-avatar" data-tone={job.company.length%4}>{job.company.slice(0,2).toUpperCase()}</div><div className="job-main"><div className="company-line">{job.company}<span>·</span>Posted: {dateText(job.posted_at)}</div>{tab==='emailed'&&job.last_emailed_at&&<p className="muted small">Last emailed: {new Date(job.last_emailed_at).toLocaleString()}</p>}{job.first_seen_at&&<p className="muted small">First discovered: {new Date(job.first_seen_at).toLocaleDateString()}</p>}<div className="job-title-row">{job.archived_at?<span className="job-title">{job.title}</span>:<button className="job-title" onClick={()=>open(job)}>{job.title}</button>}</div><div className="job-meta"><span><MapPin size={14}/>{job.location||'Location not specified'}</span><span><BriefcaseBusiness size={14}/>{job.work_mode}</span></div>{!job.archived_at&&job.evidence?.provider&&job.evidence.provider!=='dice'&&<p className="muted small">Source: <a href={job.url} target="_blank" rel="noopener noreferrer">{job.evidence.provider==='remotive'?'Remotive':job.evidence.provider==='jobicy'?'Jobicy':job.evidence.provider}</a></p>}{!job.archived_at&&job.evidence?.provider==='dice'&&<p className="muted small">Retrieved via Dice’s AI search connector. {job.evidence.company_url&&<a href={job.evidence.company_url} target="_blank" rel="noopener noreferrer">Company profile</a>}</p>}<div className="tags"><span>{job.level}</span><span className={job.match_status==='review'?'warning':'match'}>{job.match_status==='review'?'Needs review':'Title match'}</span></div>{!job.archived_at&&job.learning&&<details className="job-next-action"><summary>Why this ranking · {job.learning.adjustment>0?'+':''}{job.learning.adjustment}</summary><p>Learning version {job.learning.version}. {job.learning.enabled?(job.learning.reasons.join(' ')||'No learned adjustment: insufficient or unrelated feedback.'):'Learning paused; no ranking adjustment.'}</p></details>}{!job.archived_at&&member&&job.last_emailed_at&&<details className="job-next-action"><summary>Refine feedback (optional)</summary><label>When marking Not relevant: <select aria-label={'Relevance reason for '+job.title} value={feedback[job.id]||''} onChange={e=>setFeedback(x=>({...x,[job.id]:e.target.value}))}><option value="">No broader preference</option><option value="wrong_function">Wrong function</option><option value="wrong_seniority">Wrong seniority</option><option value="wrong_workplace">Wrong workplace type</option></select></label><p>This reason is saved only when you choose Not relevant. It cannot change the search criteria.</p></details>}{!job.archived_at&&job.next_action&&<details className="job-next-action"><summary>Next action</summary><p>{job.next_action}</p></details>}{tab==='saved'&&member&&<select aria-label={'Application status for '+job.title} value={job.stage||'saved'} onChange={e=>save(job,e.target.value)}>{['saved','applied','interviewing','offer','closed'].map(x=><option key={x}>{x}</option>)}</select>}</div><div className="application-status-column" data-status={job.archived_at?'archived':applied(job)?'applied':job.application_status||'new'}><small className="status-heading">{job.archived_at?<LockKeyhole size={13}/>:applied(job)?<CircleCheck size={13}/>:job.application_status==='submission_unknown'?<TriangleAlert size={13}/>:<Clock3 size={13}/>}APPLICATION STATUS</small>{job.archived_at&&<><span className="badge">{job.final_status==='applied'?'Successfully applied':dismissalLabels[job.final_status||'']||job.final_status}</span><small>Archived · Status locked</small></>}{member&&!job.archived_at&&<select aria-label={'Update status for '+job.title} value="" onChange={e=>updateStatus(job,e.target.value)}><option value="">Update status…</option><option value="applied">Successfully applied</option><option value="not_relevant">Not relevant</option><option value="spam">Spam</option><option value="fake_posting">Suspected fake posting</option><option value="dismissed">Dismissed</option><option value="old_posting">Old posting</option><option value="no_longer_available">No longer available</option><option value="already_applied_elsewhere">Already applied elsewhere</option></select>}{!job.archived_at&&job.dismissal_reason&&<span className="badge">Dismissed — {dismissalLabels[job.dismissal_reason]}</span>}{!job.archived_at&&<span className="badge">{applied(job)?'Successfully applied':job.application_status==='submitting'?'Submitting':job.application_status==='submission_unknown'?'Needs reconciliation':job.application_status==='needs_site_access'?'Application access needed':job.application_status==='needs_user_action'?'Action needed':job.application_status==='needs_information'?'Information needed':job.application_status==='content_review'?'Review required':'Not applied'}</span>}{applied(job)&&<small>Duplicate submission blocked</small>}</div><div className="job-actions">{!job.archived_at&&<>{member&&(job.dismissal_reason?<button className="secondary" disabled={dismissBusy} onClick={()=>dismiss(job,false)}>Restore</button>:<button className="secondary" onClick={()=>{setDismissReason('old_posting');setDismissTarget(job)}}>Dismiss job</button>)}{member&&<button className={'icon-button '+(job.saved?'is-saved':'')} aria-label={job.saved?'Unsave '+job.title:'Save '+job.title} onClick={()=>save(job)}><Bookmark size={20} fill={job.saved?'currentColor':'none'}/></button>}<a href={job.url} target="_blank" rel="noopener noreferrer" aria-label={'Open original posting for '+job.title}>{tab==='emailed'?'Open posting ':''}<ArrowUpRight size={20}/></a></>}</div></article>)}</div>

 <div className="pagination"><span>Page {page} of {Math.max(1,Math.ceil(total/25))}</span><div><button className="icon-button" aria-label="Previous page" disabled={page===1} onClick={()=>setPage(p=>p-1)}><ChevronLeft size={18}/></button><button className="icon-button" aria-label="Next page" disabled={page*25>=total} onClick={()=>setPage(p=>p+1)}><ChevronRight size={18}/></button></div></div></>}

 <footer>AI Autonomous Job Search <span>Original sources. Clear evidence. Your decision.</span></footer></section></main>


 {dismissTarget&&<div className="modal-backdrop"><section className="detail-modal" role="dialog" aria-modal="true" aria-labelledby="dismiss-title"><h2 id="dismiss-title">Dismiss job</h2><p>{dismissTarget.title} · {dismissTarget.company}</p><label>Reason<select aria-label="Dismissal reason" value={dismissReason} onChange={e=>setDismissReason(e.target.value)}>{Object.entries(dismissalLabels).map(([value,label])=><option key={value} value={value}>{label}</option>)}</select></label><p>{dismissTarget.last_emailed_at?'This permanently locks the status and moves this job to Archive. It cannot be restored or included in future reports.':'This hides the job and blocks application preparation until you restore it.'}</p><button className="primary" disabled={dismissBusy} onClick={()=>dismiss(dismissTarget,true)}>{dismissBusy?'Saving…':'Confirm dismissal'}</button><button className="secondary" disabled={dismissBusy} onClick={()=>setDismissTarget(null)}>Cancel</button></section></div>}

 {detail&&!detail.archived_at&&!lockedIds.includes(detail.id)&&<div className="modal-backdrop" onClick={()=>setDetail(null)}><section className="detail-modal" role="dialog" aria-modal="true" aria-labelledby="detail-title" onClick={e=>e.stopPropagation()}><button className="close icon-button" aria-label="Close job details" onClick={()=>setDetail(null)}><X/></button><span className="eyebrow">{detail.company}</span><h2 id="detail-title">{detail.title}</h2><p className="muted">{detail.location} · {detail.work_mode}</p><div className="message"><strong>Why this appears</strong><p>{detail.reason}</p><p>US evidence: {detail.country_status.replaceAll("_"," ")}. Leadership level: {detail.level}.</p><small>Dates come from the source. For Ashby, this is its last publication date and may reflect republication. Missing dates are excluded from date-limited searches.</small></div><dl><dt>Date posted</dt><dd>{dateText(detail.posted_at)}</dd><dt>First discovered</dt><dd>{detail.first_seen_at?new Date(detail.first_seen_at).toLocaleString():'Unknown'}</dd><dt>Last observed</dt><dd>{new Date(detail.last_seen_at).toLocaleString()}</dd></dl>{!detail.archived_at&&<a className="primary" href={detail.url} target="_blank" rel="noopener noreferrer">Original posting<ArrowUpRight size={17}/></a>}{detail.archived_at&&<p className="message">Archived · Status locked: {dismissalLabels[detail.final_status||'']||detail.final_status}</p>}{member&&!detail.archived_at&&(submissionBlocked(detail)?<p className="message">{detail.dismissal_reason?'Dismissed — '+dismissalLabels[detail.dismissal_reason]+'. Restore this job to prepare an application.':applied(detail)?'Already applied. Another submission is blocked.':'An attempt is in progress or its outcome is uncertain. Reconcile it before retrying.'}</p>:<ApplicationCheck key={detail.id} jobId={detail.id}/>)}{member&&!detail.archived_at&&<div className="detail-actions"><label>Update status<select aria-label={'Update status for '+detail.title} disabled={!!busyJob} value="" onChange={e=>updateStatus(detail,e.target.value)}><option value="">Choose an action…</option><option value="applied">Successfully applied</option>{Object.entries(dismissalLabels).map(([value,label])=><option key={value} value={value}>{label}</option>)}</select></label>{detail.dismissal_reason&&<button className="secondary" onClick={()=>dismiss(detail,false)}>Restore</button>}</div>}{!detail.archived_at&&detail.next_action&&<div className="message"><strong>Next action</strong><p>{detail.next_action}</p></div>}<h3>Job description</h3><p className="description">{detail.description}</p></section></div>}

 </div>

}
