'use client';
import {useEffect,useRef,useState} from 'react';
import Dialog from './Dialog';
import {api,idleFor,type Session} from './session';

/** How long the warning stands before the session is gone. */
export const WARNING_SECONDS=60;

/**
 * The idle limit, as a signed-in visitor sees it.
 *
 * The limit itself is the account service's: it stamps the session row on every authenticated
 * request and refuses one that has not been used for `minutes` (src/api/main.py), so nothing
 * here can keep a session alive that the server has let go. This only makes the last minute
 * visible — a small dialog a minute before, with one button that makes a request and so
 * refreshes the stamp — and, when the minute runs out, asks the account service what is left of
 * the session, which is the request that ends it and answers with no user.
 *
 * Administrators are exempt and never see it: the page renders this only for everyone else.
 */
export default function IdleWatch({minutes,onEnded}:{minutes:number;onEnded:()=>void}){
 const [remaining,setRemaining]=useState<number|null>(null);
 const [staying,setStaying]=useState(false);
 const ended=useRef(false),finish=useRef(onEnded);
 finish.current=onEnded;

 useEffect(()=>{
  if(!(minutes>0))return;
  const allowance=minutes*60*1000;
  const tick=()=>{
   const left=allowance-idleFor();
   if(left<=0){
    if(ended.current)return;
    ended.current=true;setRemaining(null);finish.current();return;
   }
   ended.current=false;
   setRemaining(left<=WARNING_SECONDS*1000?Math.ceil(left/1000):null);
  };
  tick();
  const timer=setInterval(tick,1000);
  return()=>clearInterval(timer);
 },[minutes]);

 async function stay(){
  if(staying)return;
  setStaying(true);
  // Any authenticated request refreshes the stamp; the session answer is the cheapest one,
  // and a refusal lands on the sign-in screen through the shared handler in session.ts.
  try{await api<Session>('/session');setRemaining(null)}
  catch{/* the refusal has already ended the session for the page */}
  finally{setStaying(false)}
 }

 if(remaining===null)return null;
 return <Dialog labelledBy="idle-title" onClose={stay}>
  <span className="eyebrow">STILL THERE?</span>
  <h2 id="idle-title">You will be signed out in {remaining} second{remaining===1?'':'s'}</h2>
  <p>For your security, a Bagala session ends after {minutes} minute{minutes===1?'':'s'} without activity.</p>
  <div className="account-actions"><button type="button" className="primary" disabled={staying} onClick={stay}>{staying?'Staying signed in…':'Stay signed in'}</button></div>
 </Dialog>;
}
