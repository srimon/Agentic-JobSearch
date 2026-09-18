'use client';
import {useState,type FormEvent} from 'react';
import Dialog from './Dialog';
import {withBase} from './paths';
import {PRODUCT,SITE,SITE_TITLE} from './panel.mjs';

const THANKS='Thank you. Your message has been sent.';

/** The standard header (BRAND.md, the public site): the "B" mark, the wordmark, the site title with the product's name under it ('Admin' on an admin view). Nothing else: every selection lives in the left panel. */
export function BrandHeader({product=PRODUCT}:{product?:string}){
 return <header className="site-header">
  <div className="wrap site-header__inner">
   <a className="brand" href={SITE+'/'}><span className="brand__mark" aria-hidden="true">B</span><span>Bagala</span></a>
   <span className="site-header__title">{SITE_TITLE}<span className="site-header__product">{product}</span></span>
  </div>
 </header>;
}

/** The standard footer (BRAND.md, the public site): Enquiries with Email Admin, three link columns and the copyright line. */
export function BrandFooter({onEnquiry}:{onEnquiry:()=>void}){
 const columns:[string,string,[string,string][]][]=[
  ['code','Code',[['Model API',SITE+'/model-api'],['Models',SITE+'/models'],['Documentation',SITE+'/docs'],['Model API Docs',SITE+'/docs/model-api']]],
  ['community','Community',[['GitHub','https://github.com/srimon']]],
  ['policies','Terms & policies',[['Terms of Service',SITE+'/terms'],['Privacy Policy',SITE+'/privacy']]],
 ];
 return <footer className="site-footer">
  <div className="wrap">
   <div className="footer-enquiries">
    <div><h2>Enquiries</h2><p>Questions about our products, your account or access for your organisation? Send us a message.</p></div>
    <button className="btn btn-primary" type="button" onClick={onEnquiry}>Email Admin</button>
   </div>
   <div className="footer-cols">{columns.map(([id,title,items])=><nav key={id} aria-labelledby={'footer-'+id}><h2 id={'footer-'+id}>{title}</h2><ul>{items.map(([label,href])=><li key={label}><a href={href} rel={href.startsWith(SITE)?undefined:'noopener'}>{label}</a></li>)}</ul></nav>)}</div>
   <p className="footer-copy">© 2026 Bagala.ai. All rights reserved.</p>
  </div>
 </footer>;
}

/** The Email Admin dialog, opened from the panel or the footer: Name, Email, Message and the honeypot, posted to /__hub/enquiries on this origin. */
export function EnquiryDialog({onClose}:{onClose:()=>void}){
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
  <span className="eyebrow eyebrow--account">Enquiries</span><h2 id="enquiry-title">Email Admin</h2>
  <p className="muted">Send a message to the Bagala team. We reply to the email address you give.</p>
  {sent?<><p className="message" role="status">{THANKS}</p><div className="account-actions"><button type="button" className="primary" onClick={onClose}>Close</button></div></>:
  <form className="account-form" onSubmit={submit}>
   <label>Name<input required maxLength={120} autoComplete="name" value={name} onChange={e=>setName(e.target.value)}/></label>
   <label>Email<input type="email" required maxLength={254} autoComplete="email" value={email} onChange={e=>setEmail(e.target.value)}/></label>
   <label>Message<textarea required minLength={10} maxLength={2000} rows={6} value={message} onChange={e=>setMessage(e.target.value)}/></label>
   <p className="hint">Between 10 and 2,000 characters.</p>
   <div className="brand-honeypot" aria-hidden="true"><label>Company website<input tabIndex={-1} autoComplete="off" value={website} onChange={e=>setWebsite(e.target.value)} name="company_website"/></label></div>
   {error&&<p className="message error" role="alert">{error}</p>}
   <div className="account-actions"><button className="primary" disabled={busy}>{busy?'Sending…':'Send message'}</button><button type="button" className="secondary" disabled={busy} onClick={onClose}>Cancel</button></div>
  </form>}
 </Dialog>;
}
