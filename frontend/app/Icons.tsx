/**
 * The icons of the standard shell, drawn in code: the public site's paths (platform/gateway/welcome/docs/*.html)
 * plus the few this product needs. Each renders inline, so the site's motion classes (shell.css
 * .option__icon--pulse and the others) animate it; the motion runs for everyone, by the owner's decision.
 */
import type {ReactNode} from 'react';

export type IconName='search'|'book'|'chat'|'cursor'|'mail'|'check'|'signin'|'upload'|'pencil'|'chart'|'shield'|'lock'|'help'|'document'|'orbit'|'code'|'bookmark'|'archive'|'clock'|'database'|'grid'|'gauge'|'signout'|'globe'|'sliders'|'calendar'|'layers'|'map'|'tag';
export type Motion='pulse'|'sway'|'spin'|'nudge'|'bounce'|'orbit'|'wiggle';

const PATHS:Record<IconName,ReactNode>={
 search:<><circle cx="11" cy="11" r="6.5"/><path d="M16 16l4.5 4.5"/></>,
 book:<><path d="M3 5.5c3-1 6-1 9 1 3-2 6-2 9-1v13c-3-1-6-1-9 1-3-2-6-2-9-1z"/><path d="M12 6.5v13"/></>,
 chat:<><path d="M4 5.5h16v10H9l-5 4z"/><path d="M8 9.5h8M8 12.5h5"/></>,
 cursor:<path d="M6 3l12 9-5 1 3 6-2 1-3-6-4 4z"/>,
 mail:<><rect x="3" y="5.5" width="18" height="13" rx="2"/><path d="M3.5 7l8.5 6 8.5-6"/></>,
 check:<><circle cx="12" cy="12" r="9"/><path d="M8 12.5l2.5 2.5L16 9.5"/></>,
 signin:<><circle cx="8" cy="12" r="3.5"/><path d="M11.5 12H21M18 12v3M15 12v2.5"/></>,
 upload:<><path d="M12 16V5M7.5 9.5L12 5l4.5 4.5"/><path d="M4 16v3h16v-3"/></>,
 pencil:<><path d="M4 20l4-1 10-10-3-3L5 16z"/><path d="M13 8l3 3"/></>,
 chart:<><path d="M4 19h16"/><path d="M6 16l4-5 3 3 5-7"/></>,
 shield:<><path d="M12 3l7.5 3v5.5c0 4.6-3.2 8-7.5 9.5-4.3-1.5-7.5-4.9-7.5-9.5V6z"/><path d="M9 12l2.2 2.2L15.5 10"/></>,
 lock:<><rect x="5" y="10.5" width="14" height="10" rx="2"/><path d="M8 10.5V8a4 4 0 018 0v2.5"/><path d="M12 14.5v2.5"/></>,
 help:<><circle cx="12" cy="12" r="9"/><path d="M9.5 9.5a2.5 2.5 0 015 0c0 1.5-2.5 2-2.5 3.5"/><path d="M12 17h.01"/></>,
 document:<><path d="M5 4.5h10.5l3.5 3.5v11.5H5z"/><path d="M15.5 4.5V8H19"/><path d="M8 12h8M8 15.5h8"/></>,
 orbit:<><circle cx="12" cy="12" r="2.5"/><ellipse cx="12" cy="12" rx="9" ry="3.6"/><ellipse cx="12" cy="12" rx="9" ry="3.6" transform="rotate(60 12 12)"/><ellipse cx="12" cy="12" rx="9" ry="3.6" transform="rotate(-60 12 12)"/></>,
 code:<path d="M8 8l-4 4 4 4M16 8l4 4-4 4M13.5 5l-3 14"/>,
 bookmark:<path d="M6.5 4h11v16l-5.5-4-5.5 4z"/>,
 archive:<><rect x="3" y="4.5" width="18" height="4.5" rx="1"/><path d="M4.5 9v10h15V9"/><path d="M10 13h4"/></>,
 clock:<><circle cx="12" cy="12" r="9"/><path d="M12 7v5l3.5 2"/></>,
 database:<><ellipse cx="12" cy="6" rx="7.5" ry="3"/><path d="M4.5 6v12c0 1.7 3.4 3 7.5 3s7.5-1.3 7.5-3V6"/><path d="M4.5 12c0 1.7 3.4 3 7.5 3s7.5-1.3 7.5-3"/></>,
 grid:<><rect x="4" y="4" width="6.5" height="6.5" rx="1.5"/><rect x="13.5" y="4" width="6.5" height="6.5" rx="1.5"/><rect x="4" y="13.5" width="6.5" height="6.5" rx="1.5"/><rect x="13.5" y="13.5" width="6.5" height="6.5" rx="1.5"/></>,
 gauge:<><path d="M4 16.5a8 8 0 0116 0"/><path d="M12 16.5l3.5-5"/><path d="M6 20h12"/></>,
 signout:<><path d="M10 4.5H5.5v15H10"/><path d="M14 8l4 4-4 4M9 12h9"/></>,
 globe:<><circle cx="12" cy="12" r="9"/><path d="M3 12h18M12 3c3 3.2 3 14.8 0 18M12 3c-3 3.2-3 14.8 0 18"/></>,
 sliders:<><path d="M4 7h9M17 7h3M4 17h3M11 17h9"/><circle cx="15" cy="7" r="2"/><circle cx="9" cy="17" r="2"/></>,
 calendar:<><rect x="3.5" y="5" width="17" height="15" rx="2"/><path d="M3.5 10h17M8 3v4M16 3v4"/></>,
 layers:<><path d="M12 4l8 4.5-8 4.5-8-4.5z"/><path d="M4 13l8 4.5 8-4.5"/></>,
 map:<><path d="M12 21s6-5.5 6-11a6 6 0 00-12 0c0 5.5 6 11 6 11z"/><circle cx="12" cy="10" r="2.2"/></>,
 tag:<><path d="M4 12.5V4h8.5l8 8-8.5 8.5z"/><circle cx="8.5" cy="8.5" r="1.3"/></>,
};

/** One inline icon with its motion. `small` is the panel size; otherwise the option-row size (32px). */
export function MotionIcon({name,motion,small=false,className=''}:{name:IconName;motion:Motion;small?:boolean;className?:string}){
 return <span className={(small?'side__icon ':'option__icon ')+'option__icon--'+motion+(className?' '+className:'')} aria-hidden="true"><svg viewBox="0 0 24 24">{PATHS[name]}</svg></span>;
}

export const ICON_NAMES=Object.keys(PATHS) as IconName[];
