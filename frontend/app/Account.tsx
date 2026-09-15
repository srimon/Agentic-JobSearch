'use client';
import {useEffect,useState,type FormEvent} from 'react';
import {CircleCheck,TriangleAlert,LogOut,MailCheck,KeyRound,MonitorSmartphone,UserRound} from 'lucide-react';
import {api,describeError,type User} from './session';

type Profile={username:string;display_name:string;email:string;email_verified:boolean;roles:string[];created_at?:string|null;last_login_at?:string|null};
type SessionRow={created_at:string;expires_at:string;current:boolean};
type Note={kind:'ok'|'error';text:string}|null;
const when=(value?:string|null)=>value?new Date(value).toLocaleString():'Unknown';
function Notice({note}:{note:Note}){return note?<p className={'message'+(note.kind==='error'?' error':'')} role={note.kind==='error'?'alert':'status'}>{note.text}</p>:null}

/** Account view: profile details, email verification, password change, active sessions and sign-out. */
export default function Account({user,version,onSessionChange}:{user:User;version:number;onSessionChange:()=>Promise<void>}){
 const [profile,setProfile]=useState<Profile|null>(null),[sessions,setSessions]=useState<SessionRow[]|null|undefined>(undefined),[loadNote,setLoadNote]=useState<Note>(null),[reload,setReload]=useState(0);
 const [displayName,setDisplayName]=useState(''),[email,setEmail]=useState(''),[profileNote,setProfileNote]=useState<Note>(null);
 const [current,setCurrent]=useState(''),[fresh,setFresh]=useState(''),[confirm,setConfirm]=useState(''),[passwordNote,setPasswordNote]=useState<Note>(null);
 const [sessionNote,setSessionNote]=useState<Note>(null),[confirmRevoke,setConfirmRevoke]=useState(false);
 const [busy,setBusy]=useState('');

 useEffect(()=>{let active=true;setLoadNote(null);
  api<Profile>('/auth/profile').then(p=>{if(!active)return;setProfile(p);setDisplayName(p.display_name||'');setEmail(p.email||'')}).catch(e=>{if(active)setLoadNote({kind:'error',text:describeError(e,{404:'Profile details are not available on this server yet.'})})});
  api<SessionRow[]>('/auth/sessions').then(rows=>{if(active)setSessions(Array.isArray(rows)?rows:[])}).catch(()=>{if(active)setSessions(null)});
  return()=>{active=false}},[version,reload]);

 async function run(key:string,task:()=>Promise<void>,onError:(text:string)=>void,map?:Partial<Record<number,string>>){setBusy(key);try{await task()}catch(e){onError(describeError(e,map))}finally{setBusy('')}}

 function saveProfile(e:FormEvent){e.preventDefault();if(!profile)return;
  const body:{display_name?:string;email?:string}={};
  if(displayName.trim()!==(profile.display_name||''))body.display_name=displayName.trim();
  if(email.trim()!==(profile.email||''))body.email=email.trim();
  if(!Object.keys(body).length){setProfileNote({kind:'ok',text:'Nothing has changed.'});return}
  setProfileNote(null);
  run('profile',async()=>{await api('/auth/profile',{method:'PATCH',body:JSON.stringify(body)});const p=await api<Profile>('/auth/profile');setProfile(p);setDisplayName(p.display_name||'');setEmail(p.email||'');setProfileNote({kind:'ok',text:body.email&&!p.email_verified?'Saved. Check your inbox to verify the new address.':'Saved.'});if(body.display_name)await onSessionChange()},text=>setProfileNote({kind:'error',text}),{409:'That email is already used by another account.'})}

 function resendVerification(){const address=profile?.email;if(!address)return;setProfileNote(null);
  run('resend',async()=>{await api('/auth/resend',{method:'POST',body:JSON.stringify({email:address})});setProfileNote({kind:'ok',text:`Verification email sent to ${address}.`})},text=>setProfileNote({kind:'error',text}))}

 function changePassword(e:FormEvent){e.preventDefault();setPasswordNote(null);
  if(fresh.length<15){setPasswordNote({kind:'error',text:'Use a new password of at least 15 characters.'});return}
  if(fresh!==confirm){setPasswordNote({kind:'error',text:'The new passwords do not match.'});return}
  run('password',async()=>{await api('/auth/password',{method:'POST',body:JSON.stringify({current,new:fresh})});setCurrent('');setFresh('');setConfirm('');setPasswordNote({kind:'ok',text:'Password updated.'})},text=>setPasswordNote({kind:'error',text}),{401:'The current password is wrong.'})}

 function revokeAll(){setSessionNote(null);
  run('revoke',async()=>{await api('/auth/sessions/revoke-all',{method:'POST'});setConfirmRevoke(false);setSessionNote({kind:'ok',text:'Signed out everywhere.'});await onSessionChange();setReload(r=>r+1)},text=>setSessionNote({kind:'error',text}))}

 function signOut(){run('signout',async()=>{await api('/auth/logout',{method:'POST'});location.reload()},text=>setSessionNote({kind:'error',text}))}

 const roles=profile?.roles||user.roles;
 return <div className="account">
  <section className="account-panel" aria-labelledby="account-profile"><h2 id="account-profile"><UserRound size={20}/>Profile</h2><p>How you appear across Bagala.</p>
   <Notice note={loadNote}/>
   <dl className="account-facts"><dt>Username</dt><dd>{profile?.username||user.name}</dd><dt>Roles</dt><dd><span className="roles">{roles.map(r=><span key={r}>{r}</span>)}</span></dd>{profile?.created_at&&<><dt>Member since</dt><dd>{when(profile.created_at)}</dd></>}{profile?.last_login_at&&<><dt>Last sign-in</dt><dd>{when(profile.last_login_at)}</dd></>}</dl>
   <form className="account-form" onSubmit={saveProfile}>
    <label>Display name<input required maxLength={120} autoComplete="name" value={displayName} onChange={e=>setDisplayName(e.target.value)} disabled={!profile}/></label>
    <label>Email<input type="email" required maxLength={254} autoComplete="email" value={email} onChange={e=>setEmail(e.target.value)} disabled={!profile}/></label>
    {profile&&<div className="account-actions">{profile.email_verified?<span className="verified"><CircleCheck size={14}/>Email verified</span>:<><span className="verified pending"><TriangleAlert size={14}/>Not verified</span><button type="button" className="secondary" disabled={!!busy} onClick={resendVerification}><MailCheck size={16}/>{busy==='resend'?'Sending…':'Resend verification'}</button></>}</div>}
    <Notice note={profileNote}/>
    <div className="account-actions"><button className="primary" disabled={!profile||!!busy}>{busy==='profile'?'Saving…':'Save changes'}</button></div>
   </form></section>

  <section className="account-panel" aria-labelledby="account-password"><h2 id="account-password"><KeyRound size={20}/>Password</h2><p>Use 15 to 128 characters; a long passphrase works well.</p>
   <form className="account-form" onSubmit={changePassword}>
    <label>Current password<input type="password" required autoComplete="current-password" maxLength={128} value={current} onChange={e=>setCurrent(e.target.value)}/></label>
    <label>New password<input type="password" required autoComplete="new-password" minLength={15} maxLength={128} value={fresh} onChange={e=>setFresh(e.target.value)}/></label>
    <label>Confirm new password<input type="password" required autoComplete="new-password" minLength={15} maxLength={128} value={confirm} onChange={e=>setConfirm(e.target.value)}/></label>
    <Notice note={passwordNote}/>
    <div className="account-actions"><button className="primary" disabled={!!busy}>{busy==='password'?'Updating…':'Change password'}</button></div>
   </form></section>

  <section className="account-panel" aria-labelledby="account-sessions"><h2 id="account-sessions"><MonitorSmartphone size={20}/>Signed-in devices</h2><p>Every active session for your account.</p>
   {sessions===undefined?<p className="muted">Loading sessions…</p>:sessions===null?<p className="muted">The session list is not available right now.</p>:<div className="table-wrap"><table><thead><tr><th>Started</th><th>Expires</th><th>Device</th></tr></thead><tbody>{sessions.map((s,i)=><tr key={i}><td>{when(s.created_at)}</td><td>{when(s.expires_at)}</td><td><span className="badge">{s.current?'This device':'Other device'}</span></td></tr>)}</tbody></table>{!sessions.length&&<div className="empty">No active sessions.</div>}</div>}
   <Notice note={sessionNote}/>
   <div className="account-actions">{confirmRevoke?<><span className="muted">This signs out every device, including this one.</span><button type="button" className="secondary danger" disabled={!!busy} onClick={revokeAll}>{busy==='revoke'?'Signing out…':'Confirm'}</button><button type="button" className="secondary" disabled={!!busy} onClick={()=>setConfirmRevoke(false)}>Cancel</button></>:<button type="button" className="secondary" disabled={!!busy||sessions===null} onClick={()=>setConfirmRevoke(true)}>Sign out everywhere</button>}<button type="button" className="secondary" disabled={!!busy} onClick={signOut}><LogOut size={16}/>{busy==='signout'?'Signing out…':'Sign out'}</button></div>
  </section></div>;
}
