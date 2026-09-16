'use client';
import {useState,type FormEvent} from 'react';
import {LogOut} from 'lucide-react';
import Dialog from './Dialog';
import {type User} from './session';
import {withBase} from './paths';

const SITE='https://www.bagala.ai';
const THANKS='Thank you. Your message has been sent.';

/** Bagala header bar (BRAND.md): wordmark, main title, product name, Products, Help and the account control. */
export function BrandHeader({user,hub,signingOut,onSignOut,ready=true}:{user:User|null|undefined;hub?:string;signingOut:boolean;onSignOut:()=>void;ready?:boolean}){
 return <header className="brand-header">
  <div className="brand-left">
   <a className="brand-wordmark" href={SITE+'/'}><span className="brand-mark" aria-hidden="true">B</span>Bagala</a>
   <div className="brand-titles"><span className="brand-title">Enterprise Autonomous Agentic Products</span><span className="brand-product">Job Search</span></div>
  </div>
  <nav className="brand-actions" aria-label="Bagala">
   {hub&&<a href={hub}>Products</a>}
   <a href={SITE+'/help'}>Help</a>
   {user?<span className="brand-account"><span className="brand-user" title={user.name}>{user.name}</span><button type="button" className="brand-button" disabled={signingOut} onClick={onSignOut}><LogOut size={15} aria-hidden/>{signingOut?'Signing out…':'Sign out'}</button></span>
    :ready&&<a className="brand-button" href={withBase('/')}>Sign in</a>}
  </nav>
 </header>;
}

/** Bagala footer (BRAND.md): Enquiries with the Email Admin dialog, three link columns and the copyright line. */
export function BrandFooter(){
 const [open,setOpen]=useState(false);
 const columns:[string,[string,string][]][]=[
  ['Code',[['Model API',SITE+'/model-api'],['Models',SITE+'/models'],['Documentation',SITE+'/docs'],['Model API Docs',SITE+'/docs/model-api']]],
  ['Community',[['GitHub','https://github.com/srimon']]],
  ['Terms & policies',[['Terms of Service',SITE+'/terms'],['Privacy Policy',SITE+'/privacy']]],
 ];
 return <footer className="brand-footer">
  <div className="brand-enquiries"><span>Enquiries</span><button type="button" className="brand-button" onClick={()=>setOpen(true)}>Email Admin</button></div>
  <div className="brand-columns">{columns.map(([title,items])=><div key={title}><h2>{title}</h2><ul>{items.map(([label,href])=><li key={label}><a href={href}>{label}</a></li>)}</ul></div>)}</div>
  <p className="brand-copyright">© 2026 Bagala.ai. All rights reserved.</p>
  {open&&<EnquiryDialog onClose={()=>setOpen(false)}/>}
 </footer>;
}

function EnquiryDialog({onClose}:{onClose:()=>void}){
 const [name,setName]=useState(''),[email,setEmail]=useState(''),[message,setMessage]=useState(''),[website,setWebsite]=useState('');
 const [busy,setBusy]=useState(false),[error,setError]=useState(''),[sent,setSent]=useState(false);
 async function submit(e:FormEvent){
  e.preventDefault();setError('');
  if(message.trim().length<10){setError('Enter a message of at least 10 characters.');return}
  setBusy(true);
  try{
   const res=await fetch(withBase('/__hub/enquiries'),{method:'POST',cache:'no-store',headers:{'Content-Type':'application/json'},body:JSON.stringify({name:name.trim(),email:email.trim(),message:message.trim(),company_website:website,page:window.location.pathname.slice(0,200)})});
   if(res.ok){setSent(true);return}
   const data=await res.json().catch(()=>({})) as {detail?:unknown};
   setError(res.status===429?'Too many messages. Please try again later.':res.status===422&&typeof data.detail==='string'?data.detail:'Your message could not be sent. Please try again shortly.');
  }catch{setError('Cannot reach Bagala right now. Check your connection and try again.')}
  finally{setBusy(false)}
 }
 return <Dialog labelledBy="enquiry-title" onClose={()=>{if(!busy)onClose()}}>
  <span className="eyebrow">ENQUIRIES</span><h2 id="enquiry-title">Email Admin</h2>
  {sent?<><p className="message" role="status">{THANKS}</p><div className="account-actions"><button type="button" className="primary" onClick={onClose}>Close</button></div></>:
  <form className="account-form" onSubmit={submit}>
   <label>Name<input required maxLength={120} autoComplete="name" value={name} onChange={e=>setName(e.target.value)}/></label>
   <label>Email<input type="email" required maxLength={254} autoComplete="email" value={email} onChange={e=>setEmail(e.target.value)}/></label>
   <label>Message<textarea required minLength={10} maxLength={2000} rows={6} value={message} onChange={e=>setMessage(e.target.value)}/></label>
   <div className="brand-honeypot" aria-hidden="true"><label>Company website<input tabIndex={-1} autoComplete="off" value={website} onChange={e=>setWebsite(e.target.value)} name="company_website"/></label></div>
   {error&&<p className="message error" role="alert">{error}</p>}
   <div className="account-actions"><button className="primary" disabled={busy}>{busy?'Sending…':'Send message'}</button><button type="button" className="secondary" disabled={busy} onClick={onClose}>Cancel</button></div>
  </form>}
 </Dialog>;
}
