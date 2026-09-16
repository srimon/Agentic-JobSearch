'use client';
import {createContext,useContext} from 'react';
import {withBase} from './paths';

export type User={name:string;roles:string[]};
export type Links={hub?:string;library?:string;prep?:string;governance?:string;clickhouse?:string};
export type Session={user:User|null;identity_ready?:boolean;signup_enabled?:boolean;idle_minutes?:number;links?:Partial<Record<string,unknown>>|null;features?:{data_management?:boolean;maintenance?:boolean}};

/**
 * When this browser last asked the account service for something.
 *
 * The idle limit is the server's (src/api/main.py stamps the session row on every authenticated
 * request); this is the copy the warning dialog counts against, noted where a request is about
 * to be sent rather than when it comes back, so the dialog is never late.
 */
let activeAt=Date.now();
export function markActivity(){activeAt=Date.now()}
/** Milliseconds since the last request this browser sent. */
export function idleFor(){return Date.now()-activeAt}

/**
 * A same-origin API address on the prefix in use: apiPath('/jobs') is '/api/jobs' on
 * jobs.bagala.ai and '/jobsearch/api/jobs' on bagala.ai/jobsearch/. Builds a URL and nothing
 * else, so it is safe in a render (an iframe source, a download link).
 */
export function apiPath(path:string):string{return withBase('/api'+path)}

/** One authenticated request to the API, and the moment this browser was last in touch. */
export function apiFetch(path:string,init?:RequestInit):Promise<Response>{markActivity();return fetch(apiPath(path),init)}

/** The application's own pages on the prefix in use; '/' is the sign-in landing. */
export const appPath=withBase;

/** Told when a request is refused because the session has ended, so the page can land on sign-in. */
let sessionEnded:((message:string)=>void)|null=null;
export function whenSessionEnds(handler:((message:string)=>void)|null){sessionEnded=handler}
const ENDED_MESSAGE='Your session ended. Sign in again to continue.';

/** HTTP failure with the status and the server's detail text; status 0 means the request never reached the server. */
export class ApiError extends Error{
 status:number;retryAfter:number|null;
 constructor(message:string,status:number,retryAfter:number|null=null){super(message);this.name='ApiError';this.status=status;this.retryAfter=retryAfter}
}

const NETWORK_MESSAGE='Cannot reach Bagala right now. Check your connection and try again.';

function detailText(detail:unknown):string{
 if(typeof detail==='string')return detail;
 if(Array.isArray(detail))return detail.map(item=>{const e=item as {msg?:string;loc?:unknown[]};const field=Array.isArray(e.loc)?String(e.loc[e.loc.length-1]):'';return (field&&field!=='body'?field.replaceAll('_',' ')+': ':'')+(e.msg||'')}).filter(Boolean).join(' ');
 if(detail&&typeof detail==='object'&&typeof (detail as {msg?:unknown}).msg==='string')return (detail as {msg:string}).msg;
 return '';
}

function retryAfterSeconds(header:string|null):number|null{
 if(!header)return null;
 if(/^\d+$/.test(header))return Math.max(1,Number(header));
 const at=Date.parse(header);return Number.isNaN(at)?null:Math.max(1,Math.ceil((at-Date.now())/1000));
}

export async function api<T>(path:string,init?:RequestInit):Promise<T>{
 let res:Response;
 try{res=await apiFetch(path,{...init,cache:'no-store',headers:{'Content-Type':'application/json',...init?.headers}})}
 catch{throw new ApiError(NETWORK_MESSAGE,0)}
 if(!res.ok){const data=await res.json().catch(()=>({}));
  const detail=detailText((data as {detail?:unknown}).detail);
  // A refused session (expired, idle or revoked) is not an error to show inside the workspace:
  // the page lands on the sign-in screen with the reason the account service gave.
  if(res.status===401&&path!=='/session')sessionEnded?.(detail||ENDED_MESSAGE);
  throw new ApiError(detail||'Unable to load data. Please try again.',res.status,retryAfterSeconds(res.headers.get('Retry-After')))}
 const text=await res.text();
 return (text?JSON.parse(text):undefined) as T;
}

/**
 * Ends the shared Bagala session and lands on the sign-in screen ("/"), ready to sign in again.
 * A 401 means the session had already ended, which is the goal, so it still goes to sign-in;
 * any other failure throws so the caller can say the sign-out did not happen.
 */
export async function signOutToSignIn():Promise<void>{
 let res:Response;
 try{res=await apiFetch('/auth/logout',{method:'POST',cache:'no-store',headers:{'Content-Type':'application/json'}})}
 catch{throw new ApiError(NETWORK_MESSAGE,0)}
 if(!res.ok&&res.status!==401){const data=await res.json().catch(()=>({}));throw new ApiError(detailText((data as {detail?:unknown}).detail)||'Could not sign out. Please try again.',res.status)}
 window.location.assign(appPath('/'));
}

/** Human copy for a failed request; `map` overrides the wording for specific status codes. */
export function describeError(e:unknown,map:Partial<Record<number,string>>={}):string{
 if(!(e instanceof ApiError))return e instanceof Error&&e.message?e.message:'Something went wrong. Please try again.';
 if(e.status===0)return e.message;
 if(e.status===429)return e.retryAfter?`Too many attempts. Wait ${e.retryAfter} seconds and try again.`:'Too many attempts. Wait a moment and try again.';
 const mapped=map[e.status];if(mapped)return mapped;
 if(e.status===422)return e.message||'Check the details you entered.';
 if(e.status>=500)return 'Bagala is having trouble right now. Please try again shortly.';
 return e.message;
}

/** Old single-host addresses; used only when the session carries no `links` object at all. */
export const legacyLinks:Links={hub:'http://localhost:3180/',prep:'http://localhost:3188/',governance:'http://localhost:3186/',clickhouse:'http://localhost:3187/'};

export function resolveLinks(session:Session|null):Links{
 const raw=session?.links;
 if(!raw||typeof raw!=='object')return {...legacyLinks};
 const pick=(...keys:string[])=>{for(const key of keys){const value=raw[key];if(typeof value==='string'&&value)return value}return undefined};
 return {hub:pick('hub'),library:pick('library'),prep:pick('prep','training'),governance:pick('governance','openmetadata'),clickhouse:pick('clickhouse','clickhouse_console')};
}

export function joinUrl(base:string,path:string):string{return base.replace(/\/+$/,'')+'/'+path.replace(/^\/+/,'')}

/** Job Search → Job Prep hand-off (BRAND.md): `<prep>start?role=…&company=…&source=jobsearch`, each value ≤ 200 characters. */
export function prepStartUrl(prep:string,title:string,company:string):string{
 const base=prep.endsWith('/')?prep:prep+'/';
 const clip=(value:string)=>(value||'').trim().slice(0,200);
 return base+'start?role='+encodeURIComponent(clip(title))+'&company='+encodeURIComponent(clip(company))+'&source=jobsearch';
}

export const isOperator=(user:User|null|undefined)=>!!user?.roles.some(r=>['operator','administrator'].includes(r));
/** Monitoring and operational displays (sources, activity, collection status, observability, data management, learning management) are administrator-only. */
export const isAdministrator=(user:User|null|undefined)=>!!user?.roles.includes('administrator');

/** `operator` carries administrator access: embedded operational screens show console links only to administrators. */
export type HubContext={links:Links;operator:boolean};
export const HubLinksContext=createContext<HubContext>({links:legacyLinks,operator:false});
export const useHubLinks=()=>useContext(HubLinksContext);

/** Accepts a return address only when it is same-origin or an https bagala.ai address. */
export function safeNext(raw:string|null|undefined):string|null{
 if(!raw)return null;
 let url:URL;try{url=new URL(raw,window.location.origin)}catch{return null}
 if(url.origin===window.location.origin)return url.href;
 if(url.protocol==='https:'&&(url.hostname==='bagala.ai'||url.hostname.endsWith('.bagala.ai')))return url.href;
 return null;
}

const NEXT_KEY='jobsearch-next',NEXT_TTL=30*60*1000;
/** Keeps the return address across the create-account, verify-by-email and sign-in steps, which usually span page loads. */
export function rememberNext(url:string|null){try{if(url)localStorage.setItem(NEXT_KEY,JSON.stringify({url,until:Date.now()+NEXT_TTL}));else localStorage.removeItem(NEXT_KEY)}catch{}}
export function recallNext():string|null{try{const stored=JSON.parse(localStorage.getItem(NEXT_KEY)||'null') as {url?:string;until?:number}|null;if(stored?.url&&typeof stored.until==='number'&&stored.until>Date.now())return safeNext(stored.url);localStorage.removeItem(NEXT_KEY)}catch{}return null}

/** Removes handled query parameters (tokens) from the address bar without reloading. */
export function stripParams(...keys:string[]){const url=new URL(window.location.href);keys.forEach(k=>url.searchParams.delete(k));window.history.replaceState(null,'',url.pathname+url.search+url.hash)}
