 'use client';
import {useEffect,useState} from 'react';
import {Pause,Play,LoaderCircle,Save} from 'lucide-react';
export default function MotionScene({loading,saving,label}:{loading:boolean;saving:boolean;label:string}){
 const [paused,setPaused]=useState(false);
 useEffect(()=>{try{setPaused(localStorage.getItem('jobsearch-motion')==='paused'||matchMedia('(prefers-reduced-motion: reduce)').matches)}catch{}},[]);
 useEffect(()=>{document.documentElement.dataset.motion=paused?'paused':'on';return()=>{delete document.documentElement.dataset.motion}},[paused]);
 function toggle(){setPaused(p=>{try{localStorage.setItem('jobsearch-motion',p?'on':'paused')}catch{}return !p})}
 return <><div className="motion-background" aria-hidden="true"><svg viewBox="0 0 1400 1000" preserveAspectRatio="xMidYMid slice"><defs><radialGradient id="ambientTeal"><stop stopColor="#DDB449" stopOpacity=".28"/><stop offset="1" stopColor="#DDB449" stopOpacity="0"/></radialGradient><radialGradient id="ambientBlue"><stop stopColor="#C99A2E" stopOpacity=".18"/><stop offset="1" stopColor="#C99A2E" stopOpacity="0"/></radialGradient></defs><circle className="ambient-orbit" cx="1100" cy="240" r="430" fill="url(#ambientTeal)"/><circle cx="420" cy="730" r="490" fill="url(#ambientBlue)"/><g fill="none" stroke="#B8892A" strokeWidth="1" opacity=".19">{[0,1,2,3,4,5,6,7].map(i=><path key={i} d={`M 250 ${110+i*23} C 550 ${-100+i*28}, 750 ${500+i*20}, 1420 ${130+i*35}`} />)}</g><path className="contour-flow" d="M250 202C550 12 750 570 1420 270" fill="none" stroke="#6E5200" strokeWidth="2" strokeDasharray="5 110" opacity=".35"/></svg></div>
 <button className="motion-toggle" onClick={toggle} aria-pressed={paused} aria-label={paused?'Enable decorative motion':'Pause decorative motion'}>{paused?<Play size={13}/>:<Pause size={13}/>}<span>{paused?'Motion off':'Motion on'}</span></button>
 {(loading||saving)&&<div className="operation-progress" role="status" aria-live="polite"><span className="progress-symbol">{saving?<Save size={18}/>:<LoaderCircle size={20} className="spin"/>}</span><div><strong>{saving?'Saving your decision':`Loading ${label.toLowerCase()}`}</strong><small>{saving?'Waiting for the server to confirm.':'Retrieving the latest results.'}</small><div className="indeterminate-track" role="progressbar" aria-label={saving?'Saving decision':'Loading results'}><span/></div></div></div>}</>
}
