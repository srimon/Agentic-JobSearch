'use client';
import type {ConsentChoice,ConsentNotice} from './session';

export const PURPOSES:(keyof ConsentChoice)[]=['analytics','partners','advertising'];
export const NO_CONSENT:ConsentChoice={analytics:false,partners:false,advertising:false};

/**
 * The consent notice and its three choices, word for word as the account service sends them
 * (src/auth/consent.py): shown on the sign-up form, on the phone page of the phone-scan check
 * and under Account. The sentence under the choices says which default applies to this visitor.
 */
export default function ConsentChoices({notice,optInRequired,value,onChange,disabled}:{notice:ConsentNotice;optInRequired:boolean;value:ConsentChoice;onChange:(value:ConsentChoice)=>void;disabled?:boolean}){
 return <fieldset className="consent">
  <legend>{notice.intro}</legend>
  {PURPOSES.map(purpose=><label key={purpose} className="consent-choice"><input type="checkbox" checked={value[purpose]} disabled={disabled} onChange={e=>onChange({...value,[purpose]:e.target.checked})}/><span>{notice[purpose]}</span></label>)}
  <p className="hint">{optInRequired?notice.opt_in:notice.opt_out}</p>
 </fieldset>;
}
