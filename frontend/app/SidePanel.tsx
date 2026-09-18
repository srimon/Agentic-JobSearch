'use client';
import {useEffect,useState,type ReactNode} from 'react';
import {MotionIcon,type IconName,type Motion} from './Icons';
import {isDataView,panelGroups} from './panel.mjs';
import type {Links,User} from './session';

const NARROW='(max-width: 900px)';

type Entry={id:string;label:string;icon:IconName;motion:Motion;view?:string;href?:string;action?:'signout'|'enquiry';external?:boolean;current?:boolean;fold?:boolean;accent?:string;entries?:Entry[]};
type Section={label:string;entries:Entry[]};
type Subgroup={id:string;label:string;accent:string;entries?:Entry[];sections?:Section[]};
type Group={id:string;label:string;accent:string;name?:string|null;entries:Entry[];subgroups:Subgroup[]};

/**
 * The left panel of the standard shell: every selection on the page, from panel.mjs. A <details> that is open on a
 * wide screen and a drawer on a narrow one (closed until Menu is chosen, closed again after a choice), as the
 * public site's shell.js does it. In-app entries switch the pane; the others are links to the site and the products.
 *
 * The Admin group's Data management row is a fold (a <details> of its own): closed until its row is pressed, open
 * by itself on one of its views, and closed again when any other entry is chosen or the view changes to another.
 *
 * Until the page has read the address's ?view= (`viewReady`, page.tsx) the panel is its shell alone - the Menu
 * toggle and an empty nav - so the prerendered HTML and the first client render never show one context's groups on
 * an address that names the other.
 */
export default function SidePanel({user,links,tab,viewReady,own,signIn,ready,signingOut,choose,onSignOut,onEnquiry}:
 {user:User|null|undefined;links:Links;tab:string;viewReady:boolean;own:string;signIn:string;ready:boolean;signingOut:boolean;choose:(view:string)=>void;onSignOut:()=>void;onEnquiry:()=>void}){
 const [open,setOpen]=useState(true);
 useEffect(()=>{
  const narrow=window.matchMedia(NARROW);
  const fit=()=>setOpen(!narrow.matches);
  fit();
  narrow.addEventListener('change',fit);
  return()=>narrow.removeEventListener('change',fit);
 },[]);
 // The fold follows the view: open on a data view, closed on any other; pressing its row toggles it in between.
 const [foldOpen,setFoldOpen]=useState(false);
 useEffect(()=>{setFoldOpen(isDataView(tab))},[tab]);
 const groups=(viewReady?panelGroups({user:user||null,links,own,signIn,tab}):[]) as Group[];
 const settle=()=>{if(window.matchMedia(NARROW).matches)setOpen(false)};
 const pick=(view:string)=>{choose(view);setFoldOpen(isDataView(view));settle()};
 const leave=()=>{setFoldOpen(false);settle()};

 const item=(e:Entry):ReactNode=>{
  const icon=<MotionIcon name={e.icon} motion={e.motion} small/>;
  if(e.fold)return <details className={'side__fold side__group--'+(e.accent||'data')} open={foldOpen} onToggle={event=>setFoldOpen(event.currentTarget.open)}>
   <summary className="side__fold__summary" id={'side-admin-'+e.id}>{icon}{e.label}</summary>
   {list(e.entries||[])}
  </details>;
  if(e.action==='signout')return <button type="button" className="side__button" disabled={signingOut} onClick={()=>{onSignOut();leave()}}>{icon}{signingOut?'Signing out…':e.label}</button>;
  if(e.action==='enquiry')return <button type="button" className="side__button" onClick={()=>{onEnquiry();leave()}}>{icon}{e.label}</button>;
  if(e.view)return <button type="button" className="side__button" aria-current={tab===e.view?'page':undefined} onClick={()=>pick(e.view!)}>{icon}{e.label}</button>;
  return <a href={e.href} aria-current={e.current?'page':undefined} onClick={leave}>{icon}{e.label}{e.external&&<span className="side__ext" aria-hidden="true">↗</span>}</a>;
 };
 const list=(entries:Entry[]):ReactNode=><ul className="side__list">{entries.map(e=><li key={e.id}>{item(e)}</li>)}</ul>;

 return <details className="side" id="side" open={open} onToggle={event=>setOpen(event.currentTarget.open)}>
  <summary className="side__toggle">Menu</summary>
  <nav className="side__nav" aria-label="Sections">
   {groups.map(group=><section key={group.id} className={'side__group side__group--'+group.accent} aria-labelledby={'side-'+group.id}>
    <h2 className="side__label" id={'side-'+group.id}>{group.label}</h2>
    {group.id==='account'&&!ready&&<p className="side__note" aria-busy="true">Checking sign-in…</p>}
    {group.name&&<span className="side__name" title={group.name}>{group.name}</span>}
    {list(group.entries)}
    {group.subgroups.map(sub=><section key={sub.id} className={'side__sub side__group--'+sub.accent} aria-labelledby={'side-'+sub.id}>
     <h3 className="side__label" id={'side-'+sub.id}>{sub.label}</h3>
     {sub.entries&&list(sub.entries)}
     {sub.sections?.map(section=><div key={section.label}><h4 className="side__sublabel">{section.label}</h4>{list(section.entries)}</div>)}
    </section>)}
   </section>)}
  </nav>
 </details>;
}
