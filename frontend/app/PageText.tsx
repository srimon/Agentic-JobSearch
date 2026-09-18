'use client';
import {useCallback,useEffect,useRef,useState} from 'react';
import {api,apiPath,describeError} from './session';
import {batchProblem,changedText,markedElements,parsePageText,readMarked,writeMarked} from './page-text.mjs';

/**
 * The administrator's words on the screen (the owner's 18 September batch, section 5).
 *
 * Mounted once by the page. It reads the shared text store (GET /api/hub/page-text on this product's own API path)
 * and replaces the text of every element marked `data-text="<page>.<slug>"` that it holds a key for - `textContent`,
 * never `innerHTML`. The source words are remembered the first time each element is seen, so Cancel and
 * "Reset this page to the original" can put them back without a reload.
 *
 * `editing` comes from the Admin group's "Edit the text on this page": the marked elements become editable and
 * outlined, and Save sends only the keys whose words actually changed. A refusal is shown and the edits stay on
 * screen. Nothing here reads or writes anything but static copy: live data, names and numbers are never marked.
 */
export default function PageText({editing,screen,onClose}:{editing:boolean;screen:string;onClose:()=>void}){
 const [stored,setStored]=useState<Record<string,string>>({});
 const [loaded,setLoaded]=useState(false);
 const [busy,setBusy]=useState(false),[error,setError]=useState(''),[note,setNote]=useState('');
 /** The words the source ships, by key, recorded the first time each marked element is seen. */
 const original=useRef<Record<string,string>>({});

 const read=useCallback(async():Promise<Record<string,string>|null>=>{
  try{const res=await fetch(apiPath('/hub/page-text'),{cache:'no-store',credentials:'same-origin'});
   if(!res.ok)return null;
   return parsePageText(await res.json()) as Record<string,string>;
  }catch{return null}
 },[]);

 useEffect(()=>{let live=true;read().then(values=>{if(!live)return;if(values)setStored(values);setLoaded(true)});return()=>{live=false}},[read]);

 // Applied again after every render that could have repainted the marked copy (a new screen, fresh overrides).
 useEffect(()=>{if(!loaded)return;const before=writeMarked(document,stored) as Record<string,string>;original.current={...before,...original.current}},[loaded,stored,screen,editing]);

 // Editing makes exactly the marked elements editable, and nothing else on the screen.
 useEffect(()=>{
  const pairs=markedElements(document) as [string,HTMLElement][];
  for(const [,element] of pairs){
   if(editing){element.setAttribute('contenteditable','true');element.setAttribute('spellcheck','false');element.classList.add('text-editing')}
   else{element.removeAttribute('contenteditable');element.removeAttribute('spellcheck');element.classList.remove('text-editing')}
  }
  return()=>{for(const [,element] of pairs){element.removeAttribute('contenteditable');element.removeAttribute('spellcheck');element.classList.remove('text-editing')}};
 },[editing,screen,stored,loaded]);

 /** Puts the source words back, then the overrides given, so a cleared key returns to what the source says. */
 function repaint(values:Record<string,string>){writeMarked(document,original.current);writeMarked(document,values)}

 async function send(batch:Record<string,string>,done:string){
  setBusy(true);setError('');setNote('');
  try{
   await api('/hub/page-text',{method:'PUT',body:JSON.stringify(batch)});
   const fresh=await read();
   const values=fresh||{};
   repaint(values);setStored(values);setNote(done);onClose();
  }catch(e){setError(describeError(e,{403:'Only an administrator may change the words on a page.'}))}
  finally{setBusy(false)}
 }

 function save(){
  const current=readMarked(document) as Record<string,string>;
  const batch=changedText(stored,current,original.current) as Record<string,string>;
  if(!Object.keys(batch).length){setError('');setNote('Nothing has changed.');onClose();return}
  const problem=batchProblem(batch) as string|null;
  if(problem){setError(problem);return}
  send(batch,'The words on this page were saved.');
 }

 function cancel(){setError('');setNote('');repaint(stored);onClose()}

 function reset(){
  const keys=Object.keys(readMarked(document) as Record<string,string>).filter(key=>key in stored);
  if(!keys.length){setError('');setNote('This page has no stored changes.');repaint(stored);onClose();return}
  send(Object.fromEntries(keys.map(key=>[key,''])),'This page was put back to its original words.');
 }

 // What happened after a save or a reset is said over the screen for a moment, then clears itself.
 useEffect(()=>{if(!note||editing)return;const timer=setTimeout(()=>setNote(''),7000);return()=>clearTimeout(timer)},[note,editing]);

 if(!editing)return note?<div className="text-edit-bar" role="status">{note}</div>:null;
 return <div className="text-edit-bar" role="region" aria-label="Edit the text on this page">
  <div><strong>Edit the text on this page</strong><span className="muted"> · Change any outlined words, then save. The text is stored as text and is never shown as markup.</span></div>
  {error&&<p className="message error" role="alert">{error}</p>}
  <div className="text-edit-actions">
   <button type="button" className="primary" disabled={busy} onClick={save}>{busy?'Saving…':'Save'}</button>
   <button type="button" className="secondary" disabled={busy} onClick={cancel}>Cancel</button>
   <button type="button" className="secondary" disabled={busy} onClick={reset}>Reset this page to the original</button>
  </div>
 </div>;
}
