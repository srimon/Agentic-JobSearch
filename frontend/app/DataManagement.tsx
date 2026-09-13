 'use client';
import {dataGroups} from './data-management';
import DataQuality from './DataQuality';
import DataModel from './DataModel';
import Governance from './Governance';
export function DataNavigation({tab,choose}:{tab:string;choose:(value:string)=>void}){return <details className="data-nav" open><summary>▦ Data Management</summary>{dataGroups.map(group=><details key={group.name} open><summary>{group.name}</summary>{group.tools.map(tool=><button key={tool.id} className={tab==='data-'+tool.id?'nav-item active':'nav-item'} aria-current={tab==='data-'+tool.id?'page':undefined} onClick={()=>choose('data-'+tool.id)}>{tool.name}</button>)}</details>)}</details>}
export default function DataManagement({tab,version}:{tab:string;version:number}){
 const id=tab.replace('data-','');const tool=dataGroups.flatMap(g=>g.tools).find(t=>t.id===id);
 if(['gx','soda','dbt'].includes(id))return <DataQuality key={id} version={version} initialEngine={id}/>;
 if(id==='model')return <DataModel version={version}/>;
 if(id==='governance'||id==='catalog')return <Governance/>;
 if(!tool)return <p>Select a data management tool.</p>;
 return <section className="dq"><div className="dq-hero"><div><span className="eyebrow">DATA MANAGEMENT · STAGING</span><h2>{tool.name}</h2><p>{tool.description}</p></div></div><p><strong>{tool.status}</strong></p>{tool.url?<a className="primary" href={tool.url} target="_blank" rel="noopener noreferrer">Open {tool.name} ↗</a>:<button className="secondary" disabled>Not configured</button>}<p className="muted">External tools retain their own sign-in. This entry does not monitor live availability or grant additional permissions.</p></section>
}
