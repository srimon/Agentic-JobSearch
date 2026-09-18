'use client';

import {useEffect,useMemo,useState,useRef} from 'react';
import MotionScene from './MotionScene';
import Observability from './Observability';
import AdminConsole from './AdminConsole';
import DataQuality from './DataQuality';
import DataModel from './DataModel';
import Governance from './Governance';
import DataManagement from './DataManagement';
import {dataGroups} from './data-management';
import SearchOverview from './SearchOverview';
import Learning from './Learning';
import CollectionStatus from './CollectionStatus';
import DailyWorkflow from './DailyWorkflow';
import JobBoards from './JobBoards';
import Intake from './Intake';
import ApplicationCheck,{Applications} from './ApplicationCheck';
import SignIn from './SignIn';
import Account from './Account';
import Dialog from './Dialog';
import IdleWatch from './IdleWatch';
import {BrandHeader,BrandFooter,EnquiryDialog} from './Brand';
import SidePanel,{SideDivider} from './SidePanel';
import PageText from './PageText';
import {MotionIcon} from './Icons';
import {isOwnAddress} from './paths';
import {accountScreen,signedOutLanding} from './account-screen.mjs';
import {DISCIPLINES} from './disciplines.mjs';
import {ADMIN_VIEWS,GROUP_LABELS,PRODUCT,viewGroup} from './panel.mjs';
import {api,type Session,resolveLinks,prepStartUrl,isAdministrator,HubLinksContext,signOutToSignIn,describeError,safeNext,rememberNext,whenSessionEnds,appPath} from './session';

import {CircleCheck,TriangleAlert,Clock3,LockKeyhole,Bookmark,ArrowUpRight,MapPin,BriefcaseBusiness,ChevronLeft,ChevronRight,RefreshCw,X,SlidersHorizontal} from 'lucide-react';



type Job={learning?:{adjustment:number;reasons:string[];version:number;enabled:boolean};next_action?:string|null;archived_at?:string|null;final_status?:string|null;last_emailed_at?:string|null;dismissal_reason?:string|null;first_seen_at?:string;application_status?:string|null;id:string;title:string;company:string;location:string;work_mode:string;level:string;match_status:string;reason:string;posted_at:string|null;last_seen_at:string;url:string;saved:boolean;stage:string|null;description?:string;country_status:string;evidence?:{provider?:string;company_url?:string}};

type Source={id:number;company:string;provider:string;board:string;enabled:boolean;last_success_at:string|null;last_error:string|null;latest_status:string|null;fetched:number|null;matched:number|null};

type Facet={value:string;label:string;count:number};
type Facets={states:Facet[];titles:Facet[]};
type JobList={items:Job[];total:number;facets?:Facets};

type Run={id:string;company:string;status:string;created_at:string;fetched:number;matched:number;error:string|null};

const dismissalLabels:Record<string,string>={spam:'Spam',fake_posting:'Suspected fake posting',not_relevant:'Not relevant',dismissed:'Dismissed',old_posting:'Old posting',already_applied_elsewhere:'Already applied elsewhere',not_interested:'Not interested',no_longer_available:'No longer available'};
const applied=(job:Job)=>job.application_status==='submitted'||['applied','interviewing','offer','closed'].includes(job.stage||'');
const submissionBlocked=(job:Job)=>!!job.archived_at||!!job.dismissal_reason||applied(job)||['submitting','submission_unknown'].includes(job.application_status||'');
const dateText=(value:string|null)=>value?new Date(value).toLocaleDateString(undefined,{month:'short',day:'numeric',year:'numeric'}):'Posting date unknown';



export default function Home(){

 const [session,setSession]=useState<Session|null>(null),[error,setError]=useState(''),[loading,setLoading]=useState(false);

 const [tab,setTab]=useState('matches'),[q,setQ]=useState(''),[query,setQuery]=useState(''),[date,setDate]=useState('24h'),[level,setLevel]=useState(''),[mode,setMode]=useState(''),[page,setPage]=useState(1);
 // Whether the address's ?view= has been read (the mount effect below sets it last). Until then the page names no
 // product, no group and no screen: the header has no product line, the panel is an empty shell and the pane has no
 // heading, so the prerendered HTML and the first client render are the same for every address and
 // https://bagala.ai/jobsearch/?view=admin never paints the Job Search scene before hydration. It starts false on the
 // server and the client alike (never `typeof window`), so nothing mismatches.
 const [viewReady,setViewReady]=useState(false);
 const [usState,setUsState]=useState(''),[titleFamily,setTitleFamily]=useState(''),[facets,setFacets]=useState<Facets>({states:[],titles:[]});
 // The Discipline filter (the owner, 18 Sep 2026): several of the ten at once, held and cleared like the other
 // list filters, sent to /api/jobs so ranking, totals and paging stay in the database (app/disciplines.mjs).
 const [disciplines,setDisciplines]=useState<string[]>([]),[disciplinesOpen,setDisciplinesOpen]=useState(false);
 // Editing the words on this screen: the Admin group's entry turns it on, PageText.tsx does the rest.
 const [editingText,setEditingText]=useState(false);
 const listSeq=useRef(0);
 const [toast,setToast]=useState<{text:string;undo?:Job}|null>(null);
 useEffect(()=>{if(!toast)return;const timer=setTimeout(()=>setToast(null),7000);return()=>clearTimeout(timer)},[toast]);

 const [sort,setSort]=useState('recommended'),[feedback,setFeedback]=useState<Record<string,string>>({});
 const changing=useRef(false);
 const [busyJob,setBusyJob]=useState<string|null>(null),[lockedIds,setLockedIds]=useState<string[]>([]);
 function finalizeLocal(id:string){setLockedIds(ids=>[...ids,id]);setItems(rows=>rows.filter(j=>j.id!==id));setDetail(null);window.location.replace(appPath('/?view=emailed&archived='+encodeURIComponent(id)))}
 const [showDismissed,setShowDismissed]=useState(false),[dismissTarget,setDismissTarget]=useState<Job|null>(null),[dismissReason,setDismissReason]=useState('old_posting'),[dismissBusy,setDismissBusy]=useState(false);
 const [items,setItems]=useState<Job[]>([]),[total,setTotal]=useState(0),[sources,setSources]=useState<Source[]>([]),[runs,setRuns]=useState<Run[]>([]),[detail,setDetail]=useState<Job|null>(null),[version,setVersion]=useState(0);

 const [company,setCompany]=useState(''),[provider,setProvider]=useState('ashby'),[board,setBoard]=useState(''),[notice,setNotice]=useState('');

 const dataManagementEnabled=process.env.NEXT_PUBLIC_JOBSEARCH_ENVIRONMENT==='staging'||session?.features?.data_management===true;
 const links=useMemo(()=>resolveLinks(session),[session]);
 async function refreshSession(){try{const fresh=await api<Session>('/session');setSession(fresh);if(!fresh.user&&tab==='account')choose('matches')}catch(e){setError((e as Error).message)}}
 const user=session?.user, admin=isAdministrator(user),member=!!user?.roles.some(r=>['member','administrator'].includes(r));
 const [signingOut,setSigningOut]=useState(false);
 // Why the sign-in card is showing, when it is showing because a session ended rather than
 // because nobody has signed in yet.
 const [endedNotice,setEndedNotice]=useState(''),[endedReason,setEndedReason]=useState<''|'idle'|'ended'>('');
 // Signed out: on the public site the visitor is sent to the hub's screen (below) and nothing of this page shows;
 // on the loopback name the card with its form shows ('card').
 const [landing,setLanding]=useState<'unknown'|'card'>('unknown');
 const idleMinutes=session?.idle_minutes??0;
 // The panel's Sign in: the hub's account screen on the public site, told to come back here; this page's own card elsewhere.
 const [signIn,setSignIn]=useState('');
 useEffect(()=>{setSignIn(accountScreen(window.location.href,safeNext(new URLSearchParams(window.location.search).get('next')))?.signIn||appPath('/'))},[]);
 // The Email Admin dialog, opened from the panel's Account group or the footer.
 const [enquiry,setEnquiry]=useState(false);
 // Any refused request lands here: the workspace is replaced by the sign-in card with the
 // reason the account service gave, instead of an error banner over a page that cannot load.
 useEffect(()=>{whenSessionEnds(message=>{setEndedNotice(message);setEndedReason('ended');setError('');setDetail(null);setSession(s=>s?{...s,user:null}:s)});return()=>whenSessionEnds(null)},[]);
 // The idle allowance has run out: ask the account service what is left, which is the request
 // that deletes the session row, and show the sign-in card with a plain message.
 async function idleEnded(){
  setEndedNotice('You were signed out after '+idleMinutes+' minute'+(idleMinutes===1?'':'s')+' without activity.');
  setEndedReason('idle');setError('');setDetail(null);
  try{setSession(await api<Session>('/session'))}catch{setSession(s=>s?{...s,user:null}:s)}
 }
 // One sign-out for the header and the sidebar: ends the shared session, then the sign-in screen.
 async function signOut(){if(signingOut)return;setSigningOut(true);try{await signOutToSignIn()}catch(e){setError(describeError(e));setSigningOut(false)}}

 // ?view= names the screen to open: every view choose() can write (the workspace, the account, every admin and data
 // view), so a reload, Back or a link from another product's panel lands on the same screen. The view is declared
 // ready in the same effect, after the tab is set, so both land in one render: the first screen is the right one.
 useEffect(()=>{const params=new URLSearchParams(window.location.search);const views=['matches','emailed','archive','saved','intake','applications','review','sources','quality','governance','account',...ADMIN_VIEWS,...dataGroups.flatMap(g=>g.tools.map(t=>'data-'+t.id))];if(views.includes(params.get('view')||'')){setTab(params.get('view')!);setDate(params.get('view')==='archive'?'any':'24h');setShowDismissed(params.get('view')==='emailed')}setViewReady(true)},[]);
 useEffect(()=>{if(!user)return;const id=new URLSearchParams(window.location.search).get('job');if(id&&/^[0-9a-f-]{36}$/i.test(id))api<Job>('/jobs/'+id).then(j=>{if(j.archived_at)setNotice('This job is archived and locked.');else setDetail(j)}).catch(e=>setError(e.message));},[user]);

 useEffect(()=>{if(!user)return;const id=new URLSearchParams(window.location.search).get('archived');if(id&&/^[0-9a-f-]{36}$/i.test(id))api<Job>('/jobs/'+id).then(j=>{if(j.archived_at)setNotice('Status saved. The job is archived and permanently locked.')}).catch(e=>setError(e.message));},[user]);
 useEffect(()=>{api<Session>('/session').then(setSession).catch(e=>setError(e.message))},[]);
 // Another product sent a signed-in visitor here to sign in (?next=...): go straight back instead of showing
 // Opportunities. One bounce per address per minute, so a product that still refuses cannot loop.
 // On the shared host several products answer on one origin, so "already here" is the address
 // under this product's own prefix, not merely the same origin.
 useEffect(()=>{if(!session?.user)return;const params=new URLSearchParams(window.location.search);const next=safeNext(params.get('next'));if(!next||isOwnAddress(next))return;
  const key='jobsearch-next-bounce:'+next;let recent=false;try{recent=Date.now()-Number(sessionStorage.getItem(key)||0)<60000;sessionStorage.setItem(key,String(Date.now()))}catch{}
  rememberNext(null);if(!recent)window.location.replace(next);else window.history.replaceState(null,'',window.location.pathname)},[session]);
 // The public hosts have one sign-in screen for every product (the hub's; docs/plans/account-screen.md there), and
 // the other products' gateways send a signed-out visitor straight to it. This page does the same as soon as the
 // session check says signed out: to the screen with this page as the return address (query kept), or, for an old
 // email landing or a phone's code, to the screen's own page with the token (account-screen.mjs). The loopback name
 // keeps the card with its form. One bounce per minute, so a screen that keeps sending a signed-out visitor back
 // cannot loop: the card, with its working form, shows instead.
 useEffect(()=>{if(!session||session.user){setLanding('unknown');return}
  const target=signedOutLanding(window.location.href,safeNext(new URLSearchParams(window.location.search).get('next')),endedReason);
  if(!target){setLanding('card');return}
  const key='jobsearch-signin-bounce';let recent=false;try{recent=Date.now()-Number(sessionStorage.getItem(key)||0)<60000;sessionStorage.setItem(key,String(Date.now()))}catch{}
  if(recent){setLanding('card');return}
  rememberNext(null);window.location.replace(target)},[session,endedReason]);

 useEffect(()=>{const timer=setTimeout(()=>{setQuery(q);setPage(1)},300);return()=>clearTimeout(timer)},[q]);

 // Every monitoring/operational display (sources, activity, review queue, daily workflow, observability, data quality,
 // data model, governance, data management, collection status, learning management) is for administrators only.
 const adminOnly=['workflow','sources','runs','review','observability','admin','quality','model','governance'];
 useEffect(()=>{if(user&&!admin&&(adminOnly.includes(tab)||tab.startsWith('data-')))choose('matches')},[user,admin,tab]);
 useEffect(()=>{if(!user)return;if(!admin&&adminOnly.includes(tab))return;if(tab.startsWith('data-')||['workflow','intake','applications','observability','admin','quality','model','governance','account'].includes(tab)){setLoading(false);return;}let active=true;const seq=++listSeq.current;setLoading(true);setError('');const params=listParams();

 const task=tab==='sources'?api<Source[]>('/sources').then(x=>{if(active)setSources(x)}):tab==='runs'?api<Run[]>('/runs').then(x=>{if(active)setRuns(x)}):api<JobList>('/jobs?'+params).then(x=>{if(active&&seq===listSeq.current){setItems(x.items);setTotal(x.total);setFacets(x.facets||{states:[],titles:[]})}});

 task.catch(e=>{if(active)setError(e.message)}).finally(()=>{if(active)setLoading(false)});return()=>{active=false};},[user,tab,query,date,level,mode,page,version,showDismissed,sort,usState,titleFamily,disciplines]);

 function listParams(){const params=new URLSearchParams({q:query,date,level,mode,page:String(page),sort,view:tab,show_dismissed:String(showDismissed)});if(usState)params.set('state',usState);if(titleFamily)params.set('title',titleFamily);if(disciplines.length)params.set('discipline',disciplines.join(','));return params}
 /** One discipline on or off; the list returns to its first page, as every other filter change does. */
 function toggleDiscipline(id:string,on:boolean){setDisciplines(chosen=>on?[...chosen,id]:chosen.filter(x=>x!==id));setPage(1)}
 // Quietly re-reads the current list (same tab, filters, order and page) without a loading state, so scroll position is kept.
 async function reconcile(){const seq=++listSeq.current;try{const x=await api<JobList>('/jobs?'+listParams());if(seq!==listSeq.current)return;if(!x.items.length&&page>1&&(page-1)*25>=x.total){setPage(p=>p-1);return}setItems(x.items);setTotal(x.total);if(x.facets)setFacets(x.facets)}catch{/* the optimistic list stays until the next refresh */}}
 function choose(value:string){window.history.replaceState(null,'','?view='+value);setDate(value==='archive'?'any':'24h');if(['emailed','archive'].includes(value)){setQ('');setQuery('');setLevel('');setMode('');setUsState('');setTitleFamily('');setDisciplines([])}setShowDismissed(value==='emailed');setTab(value);setPage(1);setDetail(null);setNotice('')}

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
  changing.current=true;setDismissBusy(true);
  // Dismissing never changes tab, filters, search, order or scroll: the job leaves this list at once and the list is
  // reconciled quietly after the server confirms. An emailed job is archived (locked) instead, so it has no Undo.
  const archiving=dismissed&&!!job.last_emailed_at,undoable=dismissed&&!archiving&&!job.dismissal_reason,before={items,total};
  if(dismissed){
   setDismissTarget(null);setDetail(d=>d&&d.id===job.id?null:d);
   if(showDismissed&&!archiving)setItems(rows=>rows.map(j=>j.id===job.id?{...j,dismissal_reason:reason}:j));
   else{setItems(rows=>rows.filter(j=>j.id!==job.id));setTotal(n=>Math.max(0,n-1))}
  }else setBusyJob(job.id);
  try{await api('/jobs/'+job.id+'/dismissal',{method:'PUT',body:JSON.stringify({dismissed,reason,feedback_reason:reason==='not_relevant'?(feedback[job.id]||null):null})});
   if(archiving)setLockedIds(ids=>[...ids,job.id]);
   if(!dismissed){setDismissTarget(null);setDetail(null)}
   setNotice('');setToast(archiving?{text:'Job archived. Status permanently locked.'}:dismissed?{text:'Job dismissed',undo:undoable?job:undefined}:{text:'Job restored'});
   reconcile();
  }catch(e){if(dismissed){setItems(before.items);setTotal(before.total)}setError((e as Error).message)}finally{changing.current=false;setBusyJob(null);setDismissBusy(false)}
 }
 async function undoDismiss(job:Job){
  setToast(null);if(changing.current)return;changing.current=true;
  try{await api('/jobs/'+job.id+'/dismissal',{method:'PUT',body:JSON.stringify({dismissed:false})});setToast({text:'Job restored'});reconcile()}
  catch(e){setError((e as Error).message)}finally{changing.current=false}
 }
 async function open(job:Job){
  if(changing.current||job.archived_at||lockedIds.includes(job.id))return;
  try{const fresh=await api<Job>('/jobs/'+job.id);
   if(fresh.archived_at){finalizeLocal(job.id);setNotice('This job is archived and locked.');return}
   setDetail({...fresh,next_action:job.next_action});
  }catch(e){setError((e as Error).message)}
 }

 const labels:Record<string,string>={workflow:'Daily workflow',archive:'Archive',emailed:'Emailed jobs',matches:'All opportunities',saved:'Saved jobs',review:'Needs review',sources:'Source coverage',runs:'Collection runs',intake:'Resume & profile',applications:'Application checks',observability:'Observability',admin:'Admin console',quality:'Data quality',model:'Data model',governance:'Data governance',account:'Account','data-slack':'Slack notifications',...Object.fromEntries(dataGroups.flatMap(g=>g.tools.map(t=>['data-'+t.id,t.name])))};

 // The pane's group (panel.mjs): its eyebrow and headings take that group's accent, as the site's pages do. On an
 // admin view the group is Admin: the header says so, and the panel wears the standard groups without a product group.
 const group=viewGroup(tab),groupLabel=(GROUP_LABELS as Record<string,string>)[group]||PRODUCT;

 return <HubLinksContext.Provider value={{links,operator:admin}}><div className="brand-page"><a className="skip" href="#main">Skip to content</a><BrandHeader group={viewReady?group:null} product={viewReady?(groupLabel==='Account'?PRODUCT:groupLabel):null}/><div className="shell"><MotionScene loading={loading} saving={!!busyJob} label={labels[tab]}/>
 <SidePanel user={user} links={links} tab={tab} viewReady={viewReady} own={appPath('/')} signIn={signIn||appPath('/')} ready={!!session} signingOut={signingOut} choose={choose} onSignOut={signOut} onEnquiry={()=>setEnquiry(true)} onEditText={()=>setEditingText(true)}/>
 <SideDivider/>

 <main id="main" className="pane" data-group={group}>
 {session?.features?.maintenance&&<p className="notice" role="status">Scheduled maintenance · Changes to jobs, profiles and applications are temporarily disabled.</p>}

 <section className="content"><div key={viewReady?tab:''} className="page-heading page-arrival">{viewReady?<div><div className={'eyebrow eyebrow--'+group}>{groupLabel}</div><h1 data-text={'jobsearch.'+tab+'.heading'}>{labels[tab]}</h1><p data-text={'jobsearch.'+tab+'.lede'}>{tab==='emailed'?'Work through the jobs in your email reports. Selecting a status saves it immediately, permanently locks the job and moves it to Archive.':tab==='archive'?'Completed decisions are locked. Archived jobs are excluded from future reports.':tab==='sources'?'See where your opportunities come from.':tab==='runs'?'Track source checks and collection outcomes.':tab==='model'?'Explore the PostgreSQL table structure and declared relationships.':tab==='quality'?'Evidence-based checks for this application.':tab==='observability'?'Live metrics and traces, together in your workspace.':tab==='admin'?'Traffic, accounts, conversion and machine load across every Bagala product.':tab==='account'?'Your Bagala account: name, email, password, API keys and signed-in devices.':'Find the role where your experience makes a difference.'}</p></div>:<div/>}<button className="secondary" disabled={!user||loading} onClick={()=>setVersion(v=>v+1)}><RefreshCw size={16} className={loading?'spin':''}/><span data-text="jobsearch.action.refresh">Refresh</span></button></div>

 {error&&<div className="message error" role="alert">{error}<button onClick={()=>location.reload()}>Reload</button></div>}

 {viewReady&&['matches','emailed'].includes(tab)&&<SearchOverview view={tab}/>}
 {user&&admin&&['matches','emailed','saved'].includes(tab)&&<Learning onChange={()=>setVersion(v=>v+1)}/>}
 {user&&admin&&!tab.startsWith('data-')&&!['workflow','observability','admin','quality','model','governance','account'].includes(tab)&&<CollectionStatus version={version} date={date}/>}
 {notice&&<div className="message" role="status">{notice}</div>}

 {!session&&!error?<div className="empty">Connecting to your workspace…</div>:!user&&landing!=='card'?<div className="empty">Taking you to sign in…</div>:!user?<><div className="filters preview-filters"><div className="search"><MotionIcon name="search" motion="orbit" small/><input disabled placeholder="Search title or company" aria-label="Search title or company"/></div><label><span className="filter-name"><MotionIcon name="calendar" motion="bounce" small/>Date posted</span><select disabled defaultValue="Past 24 hours"><option>Any time</option><option>Past 24 hours</option><option>Past 7 days</option><option>Past 30 days</option></select></label></div><SignIn session={session} notice={endedNotice} onSession={s=>{setEndedNotice('');setSession(s)}}/></>:

 tab==='account'?<Account user={user} version={version} onSessionChange={refreshSession}/>:!admin&&adminOnly.includes(tab)?<div className="message">Administrator access is required.</div>:tab==='workflow'?<DailyWorkflow/>:tab.startsWith('data-')?(admin&&dataManagementEnabled?<DataManagement tab={tab} version={version}/>:<div className="message">Data management must be enabled and requires administrator access.</div>):tab==='governance'?(admin?<Governance/>:<div className="message">Administrator access is required.</div>):tab==='model'?(admin?<DataModel version={version}/>:<div className="message">Administrator access is required.</div>):tab==='quality'?(admin?<DataQuality version={version}/>:<div className="message">Administrator access is required.</div>):tab==='observability'?(admin?<Observability version={version}/>:<div className="message">Administrator access is required.</div>):tab==='admin'?(admin?<AdminConsole version={version}/>:<div className="message">Administrator access is required.</div>):tab==='intake'?<Intake/>:tab==='applications'?<Applications version={version}/>:tab==='sources'?<><JobBoards/><div className="table-wrap"><table><thead><tr><th>Company / board</th><th>Provider</th><th>Last successful check</th><th>Latest run</th><th>Candidates</th><th/></tr></thead><tbody>{sources.map(s=><tr key={s.id}><td><strong>{s.company}</strong><small>{s.board}</small></td><td>{s.provider}</td><td>{s.last_success_at?new Date(s.last_success_at).toLocaleString():'Never checked'}</td><td><span className={'badge '+(s.last_error?'warning':'')}>{s.last_error||s.latest_status||'Not started'}</span></td><td>{s.matched??'—'}</td><td>{admin&&<button className="secondary" onClick={async()=>{try{const r=await api<{queued:boolean}>('/sources/'+s.id+'/refresh',{method:'POST'});setNotice(r.queued?'Refresh queued.':'A refresh is already active, or this source cannot be checked again yet.');setVersion(v=>v+1)}catch(e){setError((e as Error).message)}}}>Check source</button>}</td></tr>)}</tbody></table>{!sources.length&&<div className="empty">No sources configured yet.</div>}</div>{admin&&<form className="source-form" onSubmit={async e=>{e.preventDefault();try{await api('/sources',{method:'POST',body:JSON.stringify({company,provider,board})});setCompany('');setBoard('');setVersion(v=>v+1)}catch(e){setError((e as Error).message)}}}><h2>Add an employer board</h2><p className="muted">Use the board identifier from the employer’s official careers page.</p><div className="form-row"><input required value={company} onChange={e=>setCompany(e.target.value)} placeholder="Company name" aria-label="Company name"/><select value={provider} onChange={e=>setProvider(e.target.value)} aria-label="ATS provider"><option value="ashby">Ashby</option><option value="greenhouse">Greenhouse</option><option value="lever">Lever</option></select><input required pattern="[A-Za-z0-9_-]{1,100}" value={board} onChange={e=>setBoard(e.target.value)} placeholder="Board identifier" aria-label="Board identifier"/><button className="primary">Add source</button></div></form>}</>:

 tab==='runs'?<div className="table-wrap"><table><thead><tr><th>Company</th><th>Requested</th><th>Status</th><th>Fetched</th><th>Candidates</th><th>Error</th></tr></thead><tbody>{runs.map(r=><tr key={r.id}><td>{r.company}</td><td>{new Date(r.created_at).toLocaleString()}</td><td><span className="badge">{r.status}</span></td><td>{r.fetched}</td><td>{r.matched}</td><td>{r.error||'—'}</td></tr>)}</tbody></table>{!runs.length&&<div className="empty">No collection runs yet.</div>}</div>:

 <><div className="filters"><label><span className="filter-name"><MotionIcon name="sliders" motion="sway" small/><span data-text="jobsearch.filter.order">Order</span></span><select aria-label="Job order" value={sort} onChange={e=>{setSort(e.target.value);setPage(1)}}><option value="recommended">Recommended for you</option><option value="newest">Newest first</option></select></label><div className="search"><MotionIcon name="search" motion="orbit" small/><input value={q} onChange={e=>setQ(e.target.value)} placeholder="Search title or company" aria-label="Search title or company"/></div><label><span className="filter-name"><MotionIcon name="calendar" motion="bounce" small/><span data-text="jobsearch.filter.date">Date posted</span></span><select value={date} onChange={e=>{setDate(e.target.value);setPage(1)}}><option value="any">Any time</option><option value="24h">Past 24 hours</option><option value="7d">Past 7 days</option><option value="30d">Past 30 days</option></select></label><label><span className="filter-name"><MotionIcon name="layers" motion="pulse" small/><span data-text="jobsearch.filter.level">Level</span></span><select value={level} onChange={e=>{setLevel(e.target.value);setPage(1)}}><option value="">All levels</option>{['Director','Senior Director','VP','SVP','C-suite'].map(x=><option key={x}>{x}</option>)}</select></label><label><span className="filter-name"><MotionIcon name="map" motion="wiggle" small/><span data-text="jobsearch.filter.workplace">Workplace</span></span><select value={mode} onChange={e=>{setMode(e.target.value);setPage(1)}}><option value="">All workplaces</option>{['Remote','Hybrid','On-site','Unknown'].map(x=><option key={x}>{x}</option>)}</select></label><label><span className="filter-name"><MotionIcon name="globe" motion="spin" small/><span data-text="jobsearch.filter.state">State</span></span><select aria-label="State" value={usState} onChange={e=>{setUsState(e.target.value);setPage(1)}}><option value="">All states</option>{facets.states.map(f=><option key={f.value} value={f.value}>{f.label} ({f.count})</option>)}</select></label><label><span className="filter-name"><MotionIcon name="tag" motion="nudge" small/><span data-text="jobsearch.filter.title">Job title</span></span><select aria-label="Job title" value={titleFamily} onChange={e=>{setTitleFamily(e.target.value);setPage(1)}}><option value="">All job titles</option>{facets.titles.map(f=><option key={f.value} value={f.value}>{f.label} ({f.count})</option>)}</select></label>

 {/* Discipline (the owner's ten, 18 Sep 2026): several at once, composed with every filter beside it. */}
 <details className="filter-multi" open={disciplinesOpen} onToggle={e=>setDisciplinesOpen(e.currentTarget.open)}><summary><span className="filter-name"><MotionIcon name="grid" motion="pulse" small/><span data-text="jobsearch.filter.discipline">Discipline</span></span><span className="filter-multi__state">{disciplines.length?disciplines.length+' chosen':'All disciplines'}</span></summary>
 <fieldset className="filter-multi__list"><legend className="visually-hidden">Discipline</legend>{DISCIPLINES.map(item=><label key={item.id} className="filter-multi__choice"><input type="checkbox" checked={disciplines.includes(item.id)} onChange={e=>toggleDiscipline(item.id,e.target.checked)}/>{item.label}</label>)}<button type="button" className="link-button" disabled={!disciplines.length} onClick={()=>{setDisciplines([]);setPage(1)}} data-text="jobsearch.filter.discipline-clear">Clear disciplines</button></fieldset></details></div>

 <label className="dismissed-filter"><input type="checkbox" checked={showDismissed} onChange={e=>{setShowDismissed(e.target.checked);setPage(1)}}/><MotionIcon name="archive" motion="wiggle" small/> <span data-text="jobsearch.filter.show-dismissed">Show dismissed</span></label>
 <div className="result-line"><span><strong>{loading?'…':total.toLocaleString()}</strong> {tab==='review'?'candidates to review':'opportunities'}<span className="muted"> · United States</span></span><span><SlidersHorizontal size={14}/>{sort==='recommended'&&tab!=='archive'?'Feedback ranking · newest breaks ties':tab==='emailed'?'Most recently emailed first':'Newest posted first'}</span></div>

 {date!=='any'&&<p className="filter-note" data-text="jobsearch.filter.date-note">Based on the source’s posting date. Listings with unknown dates are excluded.</p>}

 <div className={'job-list'+(loading?' results-loading':'')} aria-busy={loading}>{!loading&&!items.length?<div className="empty"><MotionIcon name="search" motion="orbit"/><h2 data-text={'jobsearch.empty.'+(tab==='emailed'?'emailed':'matches')+'.heading'}>{tab==='emailed'?'No emailed jobs to show':'No listings match these filters'}</h2><p data-text={'jobsearch.empty.'+(tab==='emailed'?'emailed':'matches')+'.lede'}>{tab==='emailed'?'Jobs appear here after Gmail accepts a tracked report. Check your filters if a job is missing.':'This view uses the employer’s posting date, not the date we discovered the job. Try a wider date range to see older verified listings.'}</p>{tab==='matches'&&date!=='any'&&<button className="secondary" onClick={()=>{setDate('any');setPage(1)}} data-text="jobsearch.empty.older-button">View older verified jobs</button>}{admin&&<button className="secondary" onClick={()=>choose('sources')} data-text="jobsearch.empty.sources-button">View sources</button>}</div>:items.filter(job=>tab==='archive'||!lockedIds.includes(job.id)).map(job=><article inert={busyJob===job.id} className={'job-card'+(job.archived_at?' job-dismissed':job.dismissal_reason?' job-dismissed':applied(job)?' job-applied':'')} key={job.id}><div className="company-avatar" data-tone={job.company.length%4}>{job.company.slice(0,2).toUpperCase()}</div><div className="job-main"><div className="company-line">{job.company}<span>·</span>Posted: {dateText(job.posted_at)}</div>{tab==='emailed'&&job.last_emailed_at&&<p className="muted small">Last emailed: {new Date(job.last_emailed_at).toLocaleString()}</p>}{job.first_seen_at&&<p className="muted small">First discovered: {new Date(job.first_seen_at).toLocaleDateString()}</p>}{job.evidence?.provider==='himalayas'&&<p className="muted small">Data sourced from {job.archived_at?'Himalayas':<a href="https://himalayas.app" target="_blank" rel="noopener noreferrer">Himalayas</a>}</p>}<div className="job-title-row">{job.archived_at?<span className="job-title">{job.title}</span>:<button className="job-title" onClick={()=>open(job)}>{job.title}</button>}</div><div className="job-meta"><span><MapPin size={14}/>{job.location||'Location not specified'}</span><span><BriefcaseBusiness size={14}/>{job.work_mode}</span></div>{!job.archived_at&&job.evidence?.provider&&job.evidence.provider!=='dice'&&<p className="muted small">Source: <a href={job.url} target="_blank" rel="noopener noreferrer">{job.evidence.provider==='remotive'?'Remotive':job.evidence.provider==='jobicy'?'Jobicy':job.evidence.provider}</a></p>}{!job.archived_at&&job.evidence?.provider==='dice'&&<p className="muted small">Retrieved via Dice’s AI search connector. {job.evidence.company_url&&<a href={job.evidence.company_url} target="_blank" rel="noopener noreferrer">Company profile</a>}</p>}<div className="tags"><span>{job.level}</span><span className={job.match_status==='review'?'warning':'match'}>{job.match_status==='review'?'Needs review':'Title match'}</span></div>{admin&&!job.archived_at&&job.learning&&<details className="job-next-action"><summary>Why this ranking · {job.learning.adjustment>0?'+':''}{job.learning.adjustment}</summary><p>Learning version {job.learning.version}. {job.learning.enabled?(job.learning.reasons.join(' ')||'No learned adjustment: insufficient or unrelated feedback.'):'Learning paused; no ranking adjustment.'}</p></details>}{!job.archived_at&&member&&job.last_emailed_at&&<details className="job-next-action"><summary>Refine feedback (optional)</summary><label>When marking Not relevant: <select aria-label={'Relevance reason for '+job.title} value={feedback[job.id]||''} onChange={e=>setFeedback(x=>({...x,[job.id]:e.target.value}))}><option value="">No broader preference</option><option value="wrong_function">Wrong function</option><option value="wrong_seniority">Wrong seniority</option><option value="wrong_workplace">Wrong workplace type</option></select></label><p>This reason is saved only when you choose Not relevant. It cannot change the search criteria.</p></details>}{!job.archived_at&&job.next_action&&<details className="job-next-action"><summary>Next action</summary><p>{job.next_action}</p></details>}{tab==='saved'&&member&&<select aria-label={'Application status for '+job.title} value={job.stage||'saved'} onChange={e=>save(job,e.target.value)}>{['saved','applied','interviewing','offer','closed'].map(x=><option key={x}>{x}</option>)}</select>}</div><div className="application-status-column" data-status={job.archived_at?'archived':applied(job)?'applied':job.application_status||'new'}><small className="status-heading">{job.archived_at?<LockKeyhole size={13}/>:applied(job)?<CircleCheck size={13}/>:job.application_status==='submission_unknown'?<TriangleAlert size={13}/>:<Clock3 size={13}/>}APPLICATION STATUS</small>{job.archived_at&&<><span className="badge">{job.final_status==='applied'?'Successfully applied':dismissalLabels[job.final_status||'']||job.final_status}</span><small>Archived · Status locked</small></>}{member&&!job.archived_at&&<select aria-label={'Update status for '+job.title} value="" onChange={e=>updateStatus(job,e.target.value)}><option value="">Update status…</option><option value="applied">Successfully applied</option><option value="not_relevant">Not relevant</option><option value="spam">Spam</option><option value="fake_posting">Suspected fake posting</option><option value="dismissed">Dismissed</option><option value="old_posting">Old posting</option><option value="no_longer_available">No longer available</option><option value="already_applied_elsewhere">Already applied elsewhere</option></select>}{!job.archived_at&&job.dismissal_reason&&<span className="badge">Dismissed — {dismissalLabels[job.dismissal_reason]}</span>}{!job.archived_at&&<span className="badge">{applied(job)?'Successfully applied':job.application_status==='submitting'?'Submitting':job.application_status==='submission_unknown'?'Needs reconciliation':job.application_status==='needs_site_access'?'Application access needed':job.application_status==='needs_user_action'?'Action needed':job.application_status==='needs_information'?'Information needed':job.application_status==='content_review'?'Review required':'Not applied'}</span>}{applied(job)&&<small>Duplicate submission blocked</small>}</div><div className="job-actions">{!job.archived_at&&<>{!job.dismissal_reason&&links.prep&&<a className="secondary" href={prepStartUrl(links.prep,job.title,job.company)} target="_blank" rel="noopener noreferrer" aria-label={'Prepare for this job: '+job.title}>Prepare for this job</a>}{member&&(job.dismissal_reason?<button className="secondary" disabled={dismissBusy} onClick={()=>dismiss(job,false)}>Restore</button>:<button className="secondary" onClick={()=>{setDismissReason('old_posting');setDismissTarget(job)}}>Dismiss job</button>)}{member&&<button className={'icon-button '+(job.saved?'is-saved':'')} aria-label={job.saved?'Unsave '+job.title:'Save '+job.title} onClick={()=>save(job)}><Bookmark size={20} fill={job.saved?'currentColor':'none'}/></button>}<a href={job.url} target="_blank" rel="noopener noreferrer" aria-label={'Open original posting for '+job.title}>{tab==='emailed'?'Open posting ':''}<ArrowUpRight size={20}/></a></>}</div></article>)}</div>

 <div className="pagination"><span>Page {page} of {Math.max(1,Math.ceil(total/25))}</span><div><button className="icon-button" aria-label="Previous page" disabled={page===1} onClick={()=>setPage(p=>p-1)}><ChevronLeft size={18}/></button><button className="icon-button" aria-label="Next page" disabled={page*25>=total} onClick={()=>setPage(p=>p+1)}><ChevronRight size={18}/></button></div></div></>}

 </section></main>


 {dismissTarget&&<Dialog labelledBy="dismiss-title" onClose={()=>{if(!dismissBusy)setDismissTarget(null)}}><h2 id="dismiss-title">Dismiss job</h2><p>{dismissTarget.title} · {dismissTarget.company}</p><label>Reason<select aria-label="Dismissal reason" value={dismissReason} onChange={e=>setDismissReason(e.target.value)}>{Object.entries(dismissalLabels).map(([value,label])=><option key={value} value={value}>{label}</option>)}</select></label><p>{dismissTarget.last_emailed_at?'This permanently locks the status and moves this job to Archive. It cannot be restored or included in future reports.':'This hides the job and blocks application preparation until you restore it.'}</p><button className="primary" disabled={dismissBusy} onClick={()=>dismiss(dismissTarget,true)}>{dismissBusy?'Saving…':'Confirm dismissal'}</button><button className="secondary" disabled={dismissBusy} onClick={()=>setDismissTarget(null)}>Cancel</button></Dialog>}

 {detail&&!detail.archived_at&&!lockedIds.includes(detail.id)&&<Dialog labelledBy="detail-title" onClose={()=>setDetail(null)}><button className="close icon-button" aria-label="Close job details" onClick={()=>setDetail(null)}><X/></button><span className="eyebrow">{detail.company}</span><h2 id="detail-title">{detail.title}</h2>{detail.evidence?.provider==='himalayas'&&<p className="muted small">Data sourced from <a href="https://himalayas.app" target="_blank" rel="noopener noreferrer">Himalayas</a>. The original posting link below returns to the source.</p>}<p className="muted">{detail.location} · {detail.work_mode}</p><div className="message"><strong>Why this appears</strong><p>{detail.reason}</p><p>US evidence: {detail.country_status.replaceAll("_"," ")}. Level: {detail.level}.</p><small>Dates come from the source. For Ashby, this is its last publication date and may reflect republication. Missing dates are excluded from date-limited searches.</small></div><dl><dt>Date posted</dt><dd>{dateText(detail.posted_at)}</dd><dt>First discovered</dt><dd>{detail.first_seen_at?new Date(detail.first_seen_at).toLocaleString():'Unknown'}</dd><dt>Last observed</dt><dd>{new Date(detail.last_seen_at).toLocaleString()}</dd></dl>{!detail.archived_at&&<a className="primary" href={detail.url} target="_blank" rel="noopener noreferrer">Original posting<ArrowUpRight size={17}/></a>}{detail.archived_at&&<p className="message">Archived · Status locked: {dismissalLabels[detail.final_status||'']||detail.final_status}</p>}{!detail.dismissal_reason&&links.prep&&<a className="secondary" href={prepStartUrl(links.prep,detail.title,detail.company)} target="_blank" rel="noopener noreferrer">Prepare for this job<ArrowUpRight size={17}/></a>}{member&&!detail.archived_at&&(submissionBlocked(detail)?<p className="message">{detail.dismissal_reason?'Dismissed — '+dismissalLabels[detail.dismissal_reason]+'. Restore this job to prepare an application.':applied(detail)?'Already applied. Another submission is blocked.':'An attempt is in progress or its outcome is uncertain. Reconcile it before retrying.'}</p>:<ApplicationCheck key={detail.id} jobId={detail.id}/>)}{member&&!detail.archived_at&&<div className="detail-actions"><label>Update status<select aria-label={'Update status for '+detail.title} disabled={!!busyJob} value="" onChange={e=>updateStatus(detail,e.target.value)}><option value="">Choose an action…</option><option value="applied">Successfully applied</option>{Object.entries(dismissalLabels).map(([value,label])=><option key={value} value={value}>{label}</option>)}</select></label>{detail.dismissal_reason&&<button className="secondary" onClick={()=>dismiss(detail,false)}>Restore</button>}</div>}{!detail.archived_at&&detail.next_action&&<div className="message"><strong>Next action</strong><p>{detail.next_action}</p></div>}<h3>Job description</h3><p className="description">{detail.description}</p></Dialog>}

 {toast&&<div className="toast" role="status" aria-live="polite"><span>{toast.text}</span>{toast.undo&&<button className="secondary" onClick={()=>undoDismiss(toast.undo!)}>Undo</button>}<button className="icon-button" aria-label="Close notification" onClick={()=>setToast(null)}><X size={16}/></button></div>}

 {/* Administrators are exempt from the idle limit, in the account service and here. */}
 {user&&!admin&&idleMinutes>0&&<IdleWatch minutes={idleMinutes} onEnded={idleEnded}/>}

 {/* The words on this screen: the overrides are read and applied for everyone; only an administrator may edit. */}
 <PageText editing={admin&&editingText} screen={viewReady?tab+':'+version:''} onClose={()=>setEditingText(false)}/>

 </div><BrandFooter onEnquiry={()=>setEnquiry(true)}/>{enquiry&&<EnquiryDialog onClose={()=>setEnquiry(false)}/>}</div></HubLinksContext.Provider>

}
