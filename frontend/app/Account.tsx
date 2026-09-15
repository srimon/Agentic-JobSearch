'use client';
import {useEffect,useState,type FormEvent} from 'react';
import {CircleCheck,TriangleAlert,LogOut,MailCheck,KeyRound,MonitorSmartphone,UserRound,ShieldCheck,Copy} from 'lucide-react';
import {api,describeError,type User} from './session';
import Dialog from './Dialog';

type Profile={username:string;display_name:string;email:string;email_verified:boolean;roles:string[];created_at?:string|null;last_login_at?:string|null;mfa_enabled?:boolean};
type MfaStatus={enabled:boolean;recovery_codes_remaining:number};
type MfaSetup={secret:string;otpauth_uri:string;qr_svg?:string|null};
type SessionRow={created_at:string;expires_at:string;current:boolean};
type Note={kind:'ok'|'error';text:string}|null;
const when=(value?:string|null)=>value?new Date(value).toLocaleString():'Unknown';
function Notice({note}:{note:Note}){return note?<p className={'message'+(note.kind==='error'?' error':'')} role={note.kind==='error'?'alert':'status'}>{note.text}</p>:null}

function CopyButton({value,label}:{value:string;label:string}){
 const [copied,setCopied]=useState(false);
 async function copy(){try{await navigator.clipboard.writeText(value);setCopied(true);setTimeout(()=>setCopied(false),2000)}catch{setCopied(false)}}
 return <button type="button" className="secondary" onClick={copy}><Copy size={16}/>{copied?'Copied':label}</button>;
}

/** Account view: profile details, email verification, password change, two-step sign-in, active sessions and sign-out. */
export default function Account({user,version,onSessionChange}:{user:User;version:number;onSessionChange:()=>Promise<void>}){
 const [profile,setProfile]=useState<Profile|null>(null),[sessions,setSessions]=useState<SessionRow[]|null|undefined>(undefined),[loadNote,setLoadNote]=useState<Note>(null),[reload,setReload]=useState(0);
 const [displayName,setDisplayName]=useState(''),[email,setEmail]=useState(''),[profileNote,setProfileNote]=useState<Note>(null);
 const [current,setCurrent]=useState(''),[fresh,setFresh]=useState(''),[confirm,setConfirm]=useState(''),[passwordNote,setPasswordNote]=useState<Note>(null);
 const [sessionNote,setSessionNote]=useState<Note>(null),[confirmRevoke,setConfirmRevoke]=useState(false);
 const [busy,setBusy]=useState('');
 const [mfa,setMfa]=useState<MfaStatus|null|undefined>(undefined),[mfaNote,setMfaNote]=useState<Note>(null);
 const [setupStep,setSetupStep]=useState<'closed'|'password'|'scan'>('closed'),[setupPassword,setSetupPassword]=useState(''),[setup,setSetup]=useState<MfaSetup|null>(null),[setupCode,setSetupCode]=useState(''),[setupNote,setSetupNote]=useState<Note>(null);
 const [recoveryCodes,setRecoveryCodes]=useState<string[]|null>(null);
 const [mfaForm,setMfaForm]=useState<'none'|'off'|'codes'>('none'),[offPassword,setOffPassword]=useState(''),[mfaCode,setMfaCode]=useState('');

 useEffect(()=>{let active=true;setLoadNote(null);
  api<Profile>('/auth/profile').then(p=>{if(!active)return;setProfile(p);setDisplayName(p.display_name||'');setEmail(p.email||'')}).catch(e=>{if(active)setLoadNote({kind:'error',text:describeError(e,{404:'Profile details are not available on this server yet.'})})});
  api<SessionRow[]>('/auth/sessions').then(rows=>{if(active)setSessions(Array.isArray(rows)?rows:[])}).catch(()=>{if(active)setSessions(null)});
  api<MfaStatus>('/auth/mfa').then(s=>{if(active)setMfa(s)}).catch(()=>{if(active)setMfa(null)});
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

 function openSetup(){setSetupStep('password');setSetupPassword('');setSetup(null);setSetupCode('');setSetupNote(null);setMfaNote(null)}
 function closeSetup(){if(busy)return;setSetupStep('closed');setSetupPassword('');setSetup(null);setSetupCode('')}

 function startSetup(e:FormEvent){e.preventDefault();setSetupNote(null);
  run('mfa-setup',async()=>{const data=await api<MfaSetup>('/auth/mfa/setup',{method:'POST',body:JSON.stringify({password:setupPassword})});setSetupPassword('');setSetup(data);setSetupStep('scan')},text=>setSetupNote({kind:'error',text}),{400:'That password is not right.',409:'Two-step sign-in is already on.'})}

 function confirmSetup(e:FormEvent){e.preventDefault();setSetupNote(null);
  run('mfa-enable',async()=>{const result=await api<{recovery_codes:string[]}>('/auth/mfa/enable',{method:'POST',body:JSON.stringify({code:setupCode.trim()})});
   setSetupStep('closed');setSetup(null);setSetupCode('');setRecoveryCodes(result.recovery_codes);setMfa({enabled:true,recovery_codes_remaining:result.recovery_codes.length});
   setMfaNote({kind:'ok',text:'Two-step sign-in is on. Other devices were signed out.'});setReload(r=>r+1)},
   text=>{setSetupCode('');setSetupNote({kind:'error',text})},{400:'That code did not work. Check the time on your phone and try the newest code.',409:'Setup expired. Close this window and start again.'})}

 function showMfaForm(form:'none'|'off'|'codes'){setMfaForm(form);setOffPassword('');setMfaCode('');setMfaNote(null)}

 function turnOff(e:FormEvent){e.preventDefault();setMfaNote(null);
  run('mfa-off',async()=>{await api('/auth/mfa/disable',{method:'POST',body:JSON.stringify({password:offPassword,code:mfaCode.trim()})});setMfaForm('none');setOffPassword('');setMfaCode('');setMfa({enabled:false,recovery_codes_remaining:0});setMfaNote({kind:'ok',text:'Two-step sign-in is off. You now sign in with your password only.'})},
   text=>{setMfaCode('');setMfaNote({kind:'error',text})},{400:'The password or code is not right.'})}

 function newCodes(e:FormEvent){e.preventDefault();setMfaNote(null);
  run('mfa-codes',async()=>{const result=await api<{recovery_codes:string[]}>('/auth/mfa/recovery-codes',{method:'POST',body:JSON.stringify({code:mfaCode.trim()})});setMfaForm('none');setMfaCode('');setRecoveryCodes(result.recovery_codes);setMfa({enabled:true,recovery_codes_remaining:result.recovery_codes.length});setMfaNote({kind:'ok',text:'New recovery codes created. The old ones no longer work.'})},
   text=>{setMfaCode('');setMfaNote({kind:'error',text})},{400:'That code did not work. Try the newest code from your app.'})}

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

  <section className="account-panel" aria-labelledby="account-mfa"><h2 id="account-mfa"><ShieldCheck size={20}/>Two-step sign-in</h2><p>Add a code from an authenticator app (such as Google Authenticator, Microsoft Authenticator or 1Password) to your password when you sign in.</p>
   {mfa===undefined?<p className="muted">Loading…</p>:mfa===null?<p className="muted">Two-step sign-in settings are not available right now.</p>:<>
    <div className="account-actions">{mfa.enabled?<span className="verified"><CircleCheck size={14}/>On</span>:<span className="verified pending"><TriangleAlert size={14}/>Off</span>}{mfa.enabled&&<span className="muted">{mfa.recovery_codes_remaining} of 10 recovery codes left</span>}</div>
    <Notice note={mfaNote}/>
    {mfa.enabled&&mfaForm==='off'&&<form className="account-form" onSubmit={turnOff}>
     <label>Password<input type="password" required autoComplete="current-password" maxLength={128} value={offPassword} onChange={e=>setOffPassword(e.target.value)}/></label>
     <label>Code from your app or a recovery code<input required autoComplete="one-time-code" autoCapitalize="none" spellCheck={false} maxLength={32} value={mfaCode} onChange={e=>setMfaCode(e.target.value)}/></label>
     <div className="account-actions"><button className="secondary danger" disabled={!!busy}>{busy==='mfa-off'?'Turning off…':'Turn off two-step sign-in'}</button><button type="button" className="secondary" disabled={!!busy} onClick={()=>showMfaForm('none')}>Cancel</button></div>
    </form>}
    {mfa.enabled&&mfaForm==='codes'&&<form className="account-form" onSubmit={newCodes}>
     <label>Code from your app or a recovery code<input required autoComplete="one-time-code" autoCapitalize="none" spellCheck={false} maxLength={32} value={mfaCode} onChange={e=>setMfaCode(e.target.value)}/></label>
     <p className="muted">Your current recovery codes stop working as soon as the new ones are created.</p>
     <div className="account-actions"><button className="primary" disabled={!!busy}>{busy==='mfa-codes'?'Creating…':'Create new recovery codes'}</button><button type="button" className="secondary" disabled={!!busy} onClick={()=>showMfaForm('none')}>Cancel</button></div>
    </form>}
    {mfaForm==='none'&&<div className="account-actions">{mfa.enabled?<><button type="button" className="secondary" disabled={!!busy} onClick={()=>showMfaForm('codes')}>New recovery codes</button><button type="button" className="secondary danger" disabled={!!busy} onClick={()=>showMfaForm('off')}>Turn off</button></>:<button type="button" className="primary" disabled={!!busy} onClick={openSetup}>Set up two-step sign-in</button>}</div>}
   </>}
  </section>

  {setupStep!=='closed'&&<Dialog labelledBy="mfa-setup-title" onClose={closeSetup}>
   <span className="eyebrow">TWO-STEP SIGN-IN</span><h2 id="mfa-setup-title">{setupStep==='password'?'Confirm your password':'Connect your authenticator app'}</h2>
   {setupStep==='password'?<form className="account-form" onSubmit={startSetup}>
    <p>Enter your password to start. You will need an authenticator app on your phone.</p>
    <label>Password<input type="password" required autoComplete="current-password" maxLength={128} value={setupPassword} onChange={e=>setSetupPassword(e.target.value)}/></label>
    <Notice note={setupNote}/>
    <div className="account-actions"><button className="primary" disabled={!!busy}>{busy==='mfa-setup'?'Checking…':'Continue'}</button><button type="button" className="secondary" disabled={!!busy} onClick={closeSetup}>Cancel</button></div>
   </form>:setup&&<form className="account-form" onSubmit={confirmSetup}>
    <p>{setup.qr_svg?'Scan this QR code with your authenticator app, or enter the setup key by hand.':'Add a new account in your authenticator app and enter this setup key by hand.'}</p>
    {setup.qr_svg&&<img className="mfa-qr" src={'data:image/svg+xml;charset=utf-8,'+encodeURIComponent(setup.qr_svg)} alt="QR code to add Bagala to your authenticator app" width={200} height={200}/>}
    <div><span className="muted">Setup key</span><br/><code className="mfa-secret">{(setup.secret.match(/.{1,4}/g)||[]).join(' ')}</code></div>
    <div className="account-actions"><CopyButton value={setup.secret} label="Copy key"/><span className="muted">Account: Bagala, time-based, 6 digits.</span></div>
    <label>6-digit code from the app<input inputMode="numeric" autoComplete="one-time-code" pattern="[0-9]{6}" required maxLength={6} value={setupCode} onChange={e=>setSetupCode(e.target.value.replace(/\D/g,'').slice(0,6))}/></label>
    <Notice note={setupNote}/>
    <div className="account-actions"><button className="primary" disabled={!!busy||setupCode.length!==6}>{busy==='mfa-enable'?'Turning on…':'Turn on'}</button><button type="button" className="secondary" disabled={!!busy} onClick={closeSetup}>Cancel</button></div>
   </form>}
  </Dialog>}

  {recoveryCodes&&<Dialog labelledBy="mfa-codes-title" onClose={()=>setRecoveryCodes(null)}>
   <span className="eyebrow">SAVE THESE NOW</span><h2 id="mfa-codes-title">Your recovery codes</h2>
   <p>If you lose your phone, each of these codes signs you in once instead of an app code. Save them now in a password manager or print them. This is the only time they are shown.</p>
   <ul className="recovery-codes">{recoveryCodes.map(c=><li key={c}><code>{c}</code></li>)}</ul>
   <div className="account-actions"><CopyButton value={recoveryCodes.join('\n')} label="Copy codes"/><button type="button" className="primary" onClick={()=>setRecoveryCodes(null)}>I have saved them</button></div>
  </Dialog>}

  <section className="account-panel" aria-labelledby="account-sessions"><h2 id="account-sessions"><MonitorSmartphone size={20}/>Signed-in devices</h2><p>Every active session for your account.</p>
   {sessions===undefined?<p className="muted">Loading sessions…</p>:sessions===null?<p className="muted">The session list is not available right now.</p>:<div className="table-wrap"><table><thead><tr><th>Started</th><th>Expires</th><th>Device</th></tr></thead><tbody>{sessions.map((s,i)=><tr key={i}><td>{when(s.created_at)}</td><td>{when(s.expires_at)}</td><td><span className="badge">{s.current?'This device':'Other device'}</span></td></tr>)}</tbody></table>{!sessions.length&&<div className="empty">No active sessions.</div>}</div>}
   <Notice note={sessionNote}/>
   <div className="account-actions">{confirmRevoke?<><span className="muted">This signs out every device, including this one.</span><button type="button" className="secondary danger" disabled={!!busy} onClick={revokeAll}>{busy==='revoke'?'Signing out…':'Confirm'}</button><button type="button" className="secondary" disabled={!!busy} onClick={()=>setConfirmRevoke(false)}>Cancel</button></>:<button type="button" className="secondary" disabled={!!busy||sessions===null} onClick={()=>setConfirmRevoke(true)}>Sign out everywhere</button>}<button type="button" className="secondary" disabled={!!busy} onClick={signOut}><LogOut size={16}/>{busy==='signout'?'Signing out…':'Sign out'}</button></div>
  </section></div>;
}
