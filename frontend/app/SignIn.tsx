'use client';
import {useEffect,useState,type FormEvent,type ReactNode} from 'react';
import {ShieldCheck,MailCheck,KeyRound,CircleCheck,TriangleAlert} from 'lucide-react';
import {api,ApiError,describeError,safeNext,rememberNext,recallNext,stripParams,type Session} from './session';
import {addressLabel} from './paths';
import {accountScreen} from './account-screen.mjs';

type Mode='signin'|'mfa'|'signup'|'forgot'|'inbox'|'verify'|'reset';
type InboxKind='signup'|'reset'|'verify';
const USERNAME_PATTERN='[a-z0-9][a-z0-9_.@+\\-]{2,127}';

/** The signed-out card: sign in (with the optional two-step code), create account, forgot password, inbox, and the email verification and password reset landings. `notice` says why the card is showing when a session has just ended. */
export default function SignIn({session,notice='',onSession}:{session:Session|null;notice?:string;onSession:(s:Session)=>void}){
 const [mode,setMode]=useState<Mode>('signin');
 const [username,setUsername]=useState(''),[password,setPassword]=useState(''),[confirm,setConfirm]=useState(''),[email,setEmail]=useState(''),[displayName,setDisplayName]=useState('');
 const [busy,setBusy]=useState(false),[error,setError]=useState(''),[cooldown,setCooldown]=useState(0),[needsVerification,setNeedsVerification]=useState(false);
 const [inbox,setInbox]=useState<{kind:InboxKind;email:string;sent:boolean}>({kind:'signup',email:'',sent:false});
 const [verifyState,setVerifyState]=useState<'pending'|'ok'|'error'>('pending');
 const [resetToken,setResetToken]=useState(''),[resetState,setResetState]=useState<'form'|'done'|'invalid'>('form');
 const [next,setNext]=useState<string|null>(null);
 const [code,setCode]=useState(''),[useRecovery,setUseRecovery]=useState(false);
 // On the public site sign-in is the hub's own screen (one for every product); the card links there and the screen comes back here.
 const [screen,setScreen]=useState<{signIn:string;create:string}|null>(null);
 const signupEnabled=session?.signup_enabled===true;

 useEffect(()=>{
  const params=new URLSearchParams(window.location.search);
  const fromUrl=safeNext(params.get('next'));
  setNext(fromUrl||recallNext());if(fromUrl)rememberNext(fromUrl);
  setScreen(accountScreen(window.location.href,fromUrl||recallNext()));
  const verifyToken=params.get('verify'),token=params.get('reset');
  if(verifyToken){
   stripParams('verify');setMode('verify');setVerifyState('pending');
   api('/auth/verify',{method:'POST',body:JSON.stringify({token:verifyToken})}).then(()=>setVerifyState('ok')).catch(e=>{setVerifyState('error');fail(e,{400:'This verification link is invalid or has expired.'})});
  }else if(token){stripParams('reset');setResetToken(token);setResetState('form');setMode('reset')}
  else if(params.has('forgot')){stripParams('forgot');setMode('forgot')}
 },[]);
 useEffect(()=>{if(cooldown<=0)return;const timer=setTimeout(()=>setCooldown(c=>c-1),1000);return()=>clearTimeout(timer)},[cooldown]);

 function fail(e:unknown,map:Partial<Record<number,string>>={}){setError(describeError(e,map));if(e instanceof ApiError&&e.status===429)setCooldown(e.retryAfter||30)}
 function go(target:Mode){setMode(target);setError('');setNeedsVerification(false);setPassword('');setConfirm('');setCode('');setUseRecovery(false)}
 const locked=busy||cooldown>0;
 const shownError=cooldown>0?`Too many attempts. Wait ${cooldown} second${cooldown===1?'':'s'} and try again.`:error;

 async function finishSignIn(){
  if(next){rememberNext(null);window.location.assign(next);return}
  onSession(await api<Session>('/session'));
 }

 async function signIn(e:FormEvent){e.preventDefault();setBusy(true);setError('');setNeedsVerification(false);
  try{const result=await api<{ok?:boolean;mfa_required?:boolean}>('/auth/login',{method:'POST',body:JSON.stringify({username:username.trim(),password})});setPassword('');
   // With two-step sign-in on, the password only opens a short challenge; the session comes after the code.
   if(result?.mfa_required){setCode('');setUseRecovery(false);setMode('mfa');return}
   await finishSignIn();
  }catch(err){setPassword('');
   if(err instanceof ApiError&&(err.status===401||err.status===403)&&/verif/i.test(err.message)){setNeedsVerification(true);setError('Verify your email before signing in. Open the link we sent you, or request a new one.')}
   else fail(err,{401:'Invalid username, email or password.',403:'This account cannot sign in here.'});
  }finally{setBusy(false)}}

 async function verifyCode(value:string){
  if(busy||cooldown>0)return;
  setBusy(true);setError('');
  try{await api('/auth/mfa/verify',{method:'POST',body:JSON.stringify(useRecovery?{recovery_code:value}:{code:value})});setCode('');await finishSignIn()}
  catch(err){setCode('');
   if(err instanceof ApiError&&err.status===400){go('signin');setError('Your sign-in attempt expired. Enter your password again.')}
   else fail(err,{401:useRecovery?'That recovery code did not work. Check it and try again.':'That code did not work. Check your authenticator app and try again.'});
  }finally{setBusy(false)}}

 function codeChanged(value:string){
  if(useRecovery){setCode(value.slice(0,32));return}
  const digits=value.replace(/\D/g,'').slice(0,6);setCode(digits);
  if(digits.length===6)verifyCode(digits);
 }

 async function signUp(e:FormEvent){e.preventDefault();
  if(password.length<15){setError('Use a password of at least 15 characters.');return}
  setBusy(true);setError('');
  try{await api('/auth/signup',{method:'POST',body:JSON.stringify({username,email,password,display_name:displayName.trim()})});setPassword('');setInbox({kind:'signup',email,sent:false});setMode('inbox')}
  catch(err){fail(err,{404:'Sign-up is closed on this site.',409:'That username is taken. Choose another one.'})}
  finally{setBusy(false)}}

 async function requestReset(e:FormEvent){e.preventDefault();setBusy(true);setError('');
  try{await api('/auth/reset-request',{method:'POST',body:JSON.stringify({email})});setInbox({kind:'reset',email,sent:false});setMode('inbox')}
  catch(err){fail(err)}finally{setBusy(false)}}

 async function send(address:string,kind:InboxKind){if(!address)return;setBusy(true);setError('');
  try{await api(kind==='reset'?'/auth/reset-request':'/auth/resend',{method:'POST',body:JSON.stringify({email:address})});setInbox({kind,email:address,sent:true});setMode('inbox')}
  catch(err){fail(err)}finally{setBusy(false)}}

 async function reset(e:FormEvent){e.preventDefault();
  if(password.length<15){setError('Use a password of at least 15 characters.');return}
  if(password!==confirm){setError('The passwords do not match.');return}
  setBusy(true);setError('');
  try{await api('/auth/reset',{method:'POST',body:JSON.stringify({token:resetToken,password})});setPassword('');setConfirm('');setResetState('done')}
  catch(err){if(err instanceof ApiError&&err.status===400)setResetState('invalid');else fail(err)}
  finally{setBusy(false)}}

 function heading():{icon:ReactNode;eyebrow:string;title:ReactNode;text:string}{
  const shield=<ShieldCheck size={32}/>;
  switch(mode){
   case 'mfa':return {icon:<KeyRound size={32}/>,eyebrow:'TWO-STEP SIGN-IN',title:<>Confirm it is you.</>,text:useRecovery?'Enter one of the recovery codes you saved when you turned on two-step sign-in. Each code works once.':'Enter the 6-digit code from your authenticator app.'};
   case 'signup':return {icon:shield,eyebrow:'CREATE YOUR ACCOUNT',title:<>Start your<br/>private search.</>,text:'One Bagala account signs you in to Job Search, Job Prep and Library. We will email you a link to verify your address.'};
   case 'forgot':return {icon:<KeyRound size={32}/>,eyebrow:'RESET YOUR PASSWORD',title:<>Forgot your<br/>password?</>,text:'Enter the email on your account and we will send you a link to choose a new password.'};
   case 'inbox':return {icon:<MailCheck size={32}/>,eyebrow:'CHECK YOUR INBOX',title:<>Check your inbox.</>,text:inbox.kind==='signup'?`We sent a verification link to ${inbox.email}. Open it to activate your account.`:inbox.kind==='reset'?`If ${inbox.email} belongs to an account, a reset link is on its way.`:'Your account still needs email verification. We can send the link again.'};
   case 'verify':return verifyState==='ok'?{icon:<CircleCheck size={32}/>,eyebrow:'EMAIL VERIFIED',title:<>You are all set.</>,text:'Your email is verified. Sign in to start your search.'}:verifyState==='error'?{icon:<TriangleAlert size={32}/>,eyebrow:'LINK NOT ACCEPTED',title:<>That link did not work.</>,text:'Enter your email and we will send a fresh verification link.'}:{icon:shield,eyebrow:'VERIFYING',title:<>One moment.</>,text:'Confirming your email address.'};
   case 'reset':return resetState==='done'?{icon:<CircleCheck size={32}/>,eyebrow:'PASSWORD UPDATED',title:<>You are all set.</>,text:'Your password has been changed.'}:resetState==='invalid'?{icon:<TriangleAlert size={32}/>,eyebrow:'LINK NOT ACCEPTED',title:<>That link did not work.</>,text:'Reset links expire after a short while. Request a new one below.'}:{icon:<KeyRound size={32}/>,eyebrow:'CHOOSE A NEW PASSWORD',title:<>Set a new password.</>,text:'Pick something long and memorable: at least 15 characters.'};
   default:return {icon:shield,eyebrow:'A PRIVATE SEARCH',title:<>Your next opportunity<br/>starts here.</>,text:'Sign in with your Bagala account to find and track opportunities.'};
  }
 }
 const {icon,eyebrow,title,text}=heading();
 const errorLine=shownError&&<p className="message error" role="alert">{shownError}{needsVerification&&<button type="button" className="link-button" onClick={()=>{setInbox({kind:'verify',email:'',sent:false});go('inbox')}}>Resend verification</button>}</p>;
 const backToSignIn=<button type="button" className="link-button" onClick={()=>go('signin')}>Back to sign in</button>;
 const emailField=<label>Email<input type="email" autoComplete="email" required maxLength={254} value={email} onChange={e=>setEmail(e.target.value)}/></label>;

 return <div className="signin-card"><div className="lock-icon">{icon}</div><span className="eyebrow">{eyebrow}</span><h2>{title}</h2><p>{text}</p>
  {notice&&mode==='signin'&&<p className="message" role="status">{notice}</p>}

  {mode==='signin'&&screen&&<div className="login-form">
   <a className="primary" href={screen.signIn}>Sign in</a>
   <div className="signin-links">{signupEnabled&&<a className="link-button" href={screen.create}>Create an account</a>}</div>
   {next&&<p className="hint">After signing in you will continue to {addressLabel(next)}.</p>}
   <p className="hint">Sign-in is one screen for every Bagala product. It brings you back here afterwards.</p>
  </div>}

  {mode==='signin'&&!screen&&<form className="login-form" onSubmit={signIn}>
   <label>Username or email<input autoComplete="username" autoCapitalize="none" spellCheck={false} required maxLength={254} value={username} onChange={e=>setUsername(e.target.value.toLowerCase())}/></label>
   <label>Password<input type="password" autoComplete="current-password" required maxLength={128} value={password} onChange={e=>setPassword(e.target.value)}/></label>
   {errorLine}
   <button className="primary" disabled={locked}>{busy?'Signing in…':'Sign in'}</button>
   <div className="signin-links"><button type="button" className="link-button" onClick={()=>go('forgot')}>Forgot password?</button>{signupEnabled&&<button type="button" className="link-button" onClick={()=>go('signup')}>Create an account</button>}</div>
   {next&&<p className="hint">After signing in you will continue to {addressLabel(next)}.</p>}
   <p className="hint">{signupEnabled?'One Bagala account signs you in to Job Search, Job Prep and Library.':'Sign-up is closed on this site. Accounts are created by your administrator.'}</p>
  </form>}

  {mode==='mfa'&&<form className="login-form" onSubmit={e=>{e.preventDefault();if(code)verifyCode(code)}}>
   {useRecovery
    ?<label>Recovery code<input key="recovery" autoComplete="off" autoCapitalize="none" spellCheck={false} required maxLength={32} placeholder="xxxxx-xxxxx" autoFocus value={code} onChange={e=>codeChanged(e.target.value)}/></label>
    :<label>Authentication code<input key="totp" inputMode="numeric" autoComplete="one-time-code" pattern="[0-9]{6}" required maxLength={6} placeholder="123456" autoFocus value={code} onChange={e=>codeChanged(e.target.value)}/></label>}
   {errorLine}
   <button className="primary" disabled={locked||!code}>{busy?'Checking…':'Continue'}</button>
   <div className="signin-links"><button type="button" className="link-button" onClick={()=>{setUseRecovery(r=>!r);setCode('');setError('')}}>{useRecovery?'Use your authenticator app instead':'Use a recovery code instead'}</button>{backToSignIn}</div>
   <p className="hint">Lost your phone and your recovery codes? Contact your administrator to turn off two-step sign-in.</p>
  </form>}

  {mode==='signup'&&<form className="login-form" onSubmit={signUp}>
   <label>Display name<input autoComplete="name" required maxLength={120} value={displayName} onChange={e=>setDisplayName(e.target.value)}/></label>
   <label>Username<input autoComplete="username" required minLength={3} maxLength={128} pattern={USERNAME_PATTERN} title="Lower-case letters, digits and . _ @ + - (3 to 128 characters)" value={username} onChange={e=>setUsername(e.target.value.toLowerCase())}/></label>
   {emailField}
   <label>Password<input type="password" autoComplete="new-password" required minLength={15} maxLength={128} value={password} onChange={e=>setPassword(e.target.value)}/><span className="hint">15 to 128 characters. A long passphrase works well.</span></label>
   {errorLine}
   <button className="primary" disabled={locked}>{busy?'Creating your account…':'Create account'}</button>
   <div className="signin-links"><button type="button" className="link-button" onClick={()=>go('signin')}>Already have an account? Sign in</button></div>
   <p className="hint">Usernames use lower-case letters, digits and . _ @ + -. We only email you to verify your address or reset your password.</p>
  </form>}

  {mode==='forgot'&&<form className="login-form" onSubmit={requestReset}>
   {emailField}
   {errorLine}
   <button className="primary" disabled={locked}>{busy?'Sending…':'Send reset link'}</button>
   <div className="signin-links">{backToSignIn}</div>
   <p className="hint">Every request is confirmed the same way, whether or not the address is registered.</p>
  </form>}

  {mode==='inbox'&&<form className="login-form" onSubmit={e=>{e.preventDefault();send(inbox.email||email,inbox.kind)}}>
   {!inbox.email&&emailField}
   {inbox.sent&&<p className="message" role="status">Sent. Give it a minute, and check your spam folder.</p>}
   {errorLine}
   <button className="secondary" disabled={locked}>{busy?'Sending…':inbox.kind==='reset'?'Resend reset link':'Resend verification email'}</button>
   <div className="signin-links">{backToSignIn}</div>
   <p className="hint">{inbox.kind==='reset'?'The link expires after a short while; request another one if it has.':'The link expires after a short while. Verify your email before your first sign-in.'}</p>
  </form>}

  {mode==='verify'&&(verifyState==='pending'?<p className="muted" role="status">Checking your link…</p>:verifyState==='ok'?<div className="login-form"><button type="button" className="primary" onClick={()=>go('signin')}>Sign in</button></div>:
   <form className="login-form" onSubmit={e=>{e.preventDefault();send(email,'signup')}}>
    {errorLine}
    {emailField}
    <button className="primary" disabled={locked}>{busy?'Sending…':'Send a new link'}</button>
    <div className="signin-links">{backToSignIn}</div>
   </form>)}

  {mode==='reset'&&(resetState==='done'?<div className="login-form"><p className="message" role="status">Password updated. Sign in with your new password.</p><button type="button" className="primary" onClick={()=>go('signin')}>Sign in</button></div>:resetState==='invalid'?<div className="login-form"><p className="message error" role="alert">This reset link is invalid or has expired.</p><button type="button" className="primary" onClick={()=>go('forgot')}>Request a new link</button><div className="signin-links">{backToSignIn}</div></div>:
   <form className="login-form" onSubmit={reset}>
    <label>New password<input type="password" autoComplete="new-password" required minLength={15} maxLength={128} value={password} onChange={e=>setPassword(e.target.value)}/><span className="hint">15 to 128 characters.</span></label>
    <label>Confirm new password<input type="password" autoComplete="new-password" required minLength={15} maxLength={128} value={confirm} onChange={e=>setConfirm(e.target.value)}/></label>
    {errorLine}
    <button className="primary" disabled={locked}>{busy?'Updating…':'Update password'}</button>
   </form>)}

  <div className="signin-tags"><span>US opportunities</span><span>Source-backed listings</span><span>Private saved jobs</span></div></div>;
}
