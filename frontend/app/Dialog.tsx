'use client';
import {useEffect,useRef,type ReactNode} from 'react';

const FOCUSABLE='a[href],button:not([disabled]),input:not([disabled]),select:not([disabled]),textarea:not([disabled]),[tabindex]:not([tabindex="-1"])';

/** Modal panel: closes on Escape or a backdrop click, keeps Tab inside, and returns focus to the opener when it closes. */
export default function Dialog({labelledBy,onClose,children}:{labelledBy:string;onClose:()=>void;children:ReactNode}){
 const panel=useRef<HTMLElement>(null),close=useRef(onClose);
 close.current=onClose;
 useEffect(()=>{
  const root:HTMLElement|null=panel.current;if(!root)return;
  const opener=document.activeElement as HTMLElement|null;
  const focusables=()=>Array.from(root.querySelectorAll<HTMLElement>(FOCUSABLE));
  (focusables()[0]||root).focus();
  function onKey(e:KeyboardEvent){
   if(e.key==='Escape'){e.preventDefault();close.current();return}
   if(e.key!=='Tab')return;
   const items=focusables();
   if(!items.length){e.preventDefault();root!.focus();return}
   const first=items[0],last=items[items.length-1],active=document.activeElement;
   const outside=!root!.contains(active);
   if(e.shiftKey&&(outside||active===first||active===root)){e.preventDefault();last.focus()}
   else if(!e.shiftKey&&(outside||active===last)){e.preventDefault();first.focus()}
  }
  document.addEventListener('keydown',onKey);
  return()=>{document.removeEventListener('keydown',onKey);opener?.focus()};
 },[]);
 return <div className="modal-backdrop" onClick={()=>close.current()}><section ref={panel} tabIndex={-1} className="detail-modal" role="dialog" aria-modal="true" aria-labelledby={labelledBy} onClick={e=>e.stopPropagation()}>{children}</section></div>;
}
