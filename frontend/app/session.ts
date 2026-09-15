'use client';
import {createContext,useContext} from 'react';

export type User={name:string;roles:string[]};
export type Links={hub?:string;library?:string;prep?:string;governance?:string;clickhouse?:string};
export type Session={user:User|null;identity_ready?:boolean;signup_enabled?:boolean;links?:Partial<Record<string,unknown>>|null;features?:{data_management?:boolean;maintenance?:boolean}};

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
 try{res=await fetch('/api'+path,{...init,cache:'no-store',headers:{'Content-Type':'application/json',...init?.headers}})}
 catch{throw new ApiError(NETWORK_MESSAGE,0)}
 if(!res.ok){const data=await res.json().catch(()=>({}));throw new ApiError(detailText((data as {detail?:unknown}).detail)||'Unable to load data. Please try again.',res.status,retryAfterSeconds(res.headers.get('Retry-After')))}
 const text=await res.text();
 return (text?JSON.parse(text):undefined) as T;
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

export const isOperator=(user:User|null|undefined)=>!!user?.roles.some(r=>['operator','administrator'].includes(r));

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
