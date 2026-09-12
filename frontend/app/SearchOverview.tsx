import {Radar,ClipboardCheck,SlidersHorizontal,ArrowRight,ExternalLink,Archive,LockKeyhole} from 'lucide-react';
export default function SearchOverview({view}:{view:string}){
 const emailed=view==='emailed';
 const steps=emailed?[
  {Icon:ExternalLink,title:'Open the posting',text:'Review the employer’s requirements.',tone:'blue'},
  {Icon:ClipboardCheck,title:'Take the next step',text:'Use the action notes on each job.',tone:'teal'},
  {Icon:Archive,title:'Update & archive',text:'A final status locks the emailed listing.',tone:'amber'}
 ]:[
  {Icon:Radar,title:'Discover',text:'Supported sources, checked on schedule.',tone:'blue'},
  {Icon:ClipboardCheck,title:'Review',text:'Compare the role with your experience.',tone:'teal'},
  {Icon:SlidersHorizontal,title:'Refine',text:'Your feedback improves future rankings.',tone:'amber'}
 ];
 return <section className={'search-overview '+(emailed?'overview-compact':'')} aria-label={emailed?'How to work through emailed jobs':'How your job search works'}>
 {!emailed&&<div className="overview-intro"><div><span className="overview-kicker"><span/>YOUR SEARCH, WITH DIRECTION</span><h2>Find the next place<br/>to make an impact.</h2><p>Explore leadership opportunities in data and AI.<br/>Build a more focused shortlist with every decision.</p><span className="private-note"><LockKeyhole size={13}/>Your profile. Your decisions.</span></div>
 <svg className="career-illustration" viewBox="0 0 400 180" role="img" aria-label="Illustration of job listings connecting to a focused shortlist and feedback loop">
 <defs><linearGradient id="cardGlow" x1="0" y1="0" x2="1" y2="1"><stop stopColor="#e0f2fe"/><stop offset="1" stopColor="#ccfbf1"/></linearGradient></defs>
 <ellipse cx="211" cy="95" rx="156" ry="72" fill="url(#cardGlow)" opacity=".6"/>
 <path d="M90 70 C160 10 230 25 299 64 M302 120 C250 170 160 169 103 128" fill="none" stroke="#6c9eb2" strokeWidth="2" strokeDasharray="5 6"/>
 <g transform="translate(35 44) rotate(-7 60 50)"><rect width="110" height="105" rx="14" fill="white" stroke="#bed5e4"/><rect x="14" y="17" width="30" height="28" rx="7" fill="#dbeafe"/><path d="M22 28h14v10H22zm4-4h6v4h-6z" fill="none" stroke="#2563eb" strokeWidth="2"/><path d="M15 61h76M15 73h61M15 85h46" stroke="#c4d3e0" strokeWidth="5" strokeLinecap="round"/></g>
 <g transform="translate(155 28)"><rect width="117" height="129" rx="14" fill="white" stroke="#91c9bc"/><rect x="14" y="16" width="34" height="30" rx="8" fill="#ccfbf1"/><path d="m23 31 6 6 11-13" fill="none" stroke="#0f766e" strokeWidth="3" strokeLinecap="round"/><path d="M15 64h86M15 77h71" stroke="#b5c9cf" strokeWidth="5" strokeLinecap="round"/><rect x="15" y="94" width="72" height="19" rx="9" fill="#d1fae5"/><circle cx="27" cy="104" r="3" fill="#059669"/><path d="M37 104h35" stroke="#059669" strokeWidth="3" strokeLinecap="round"/></g>
 <g transform="translate(304 78)"><circle r="31" fill="#fff7ed" stroke="#f3c68a"/><path d="M-13-3a14 14 0 0 1 23-8l5 4m0-11v11H4M13 3A14 14 0 0 1-10 11l-5-4m0 11V7h11" fill="none" stroke="#d97706" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round"/></g>
 <circle cx="120" cy="24" r="5" fill="#38bdf8"/><circle cx="289" cy="151" r="4" fill="#14b8a6"/><path d="M350 133v12m-6-6h12" stroke="#dba454" strokeWidth="2"/>
 </svg></div>}
 <div className="overview-steps">{steps.map(({Icon,title,text,tone},i)=><div className="overview-step" key={title}><span className={'step-icon '+tone}><Icon size={21}/></span><div><strong>{title}</strong><p>{text}</p></div>{i<2&&<ArrowRight className="step-arrow" size={16}/>}</div>)}</div>
 </section>
}
