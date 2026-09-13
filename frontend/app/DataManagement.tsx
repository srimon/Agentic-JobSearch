 'use client';
import {slackChannelUrl} from './slack-link';
import {dataGroups} from './data-management';
import DataQuality from './DataQuality';
import Analytics from './Analytics';
import DataModel from './DataModel';
import Governance from './Governance';
export function DataNavigation({tab,choose}:{tab:string;choose:(value:string)=>void}){return <><details className="data-nav" open><summary>▦ Data Management</summary>{dataGroups.map(group=><details key={group.name} open><summary>{group.name}</summary>{group.tools.map(tool=><button key={tool.id} className={tab==='data-'+tool.id?'nav-item active':'nav-item'} aria-current={tab==='data-'+tool.id?'page':undefined} onClick={()=>choose('data-'+tool.id)}>{tool.name}</button>)}</details>)}</details><section className="data-nav" aria-label="Notifications"><p className="eyebrow">Notifications</p><button className={tab==='data-slack'?'nav-item active':'nav-item'} aria-current={tab==='data-slack'?'page':undefined} onClick={()=>choose('data-slack')}>Slack — #general</button></section></>}
export default function DataManagement({tab,version}:{tab:string;version:number}){
 const id=tab.replace('data-','');const tool=dataGroups.flatMap(g=>g.tools).find(t=>t.id===id);
 if(['gx','soda','dbt'].includes(id))return <DataQuality key={id} version={version} initialEngine={id}/>;
 if(id==='clickhouse')return <Analytics version={version}/>;
 if(id==='model')return <DataModel version={version}/>;
 if(id==='governance'||id==='catalog')return <Governance/>;
 if(id==='slack')return <section className="dq"><div className="dq-hero"><div><span className="eyebrow">NOTIFICATIONS</span><h2>Slack</h2><p>Sean · #general · ENTERPRISE-AI-HUB app</p></div></div><p>Staging discovery and quality runners are configured to report successes, failures and quality findings. This page does not poll delivery status.</p>{!slackChannelUrl&&<p>The channel’s browser link has not been supplied yet.</p>}<a className="primary" href={slackChannelUrl||'https://app.slack.com/client'} target="_blank" rel="noopener noreferrer">{slackChannelUrl?'Open #general':'Open Slack'} ↗</a><p className="muted">Sign in with your Slack account. Webhook credentials are never included in this page.</p></section>;
 if(!tool)return <p>Select a data management tool.</p>;
 return <section className="dq"><div className="dq-hero"><div><span className="eyebrow">DATA MANAGEMENT · STAGING</span><h2>{tool.name}</h2><p>{tool.description}</p></div></div><p><strong>{tool.status}</strong></p>{tool.url?<a className="primary" href={tool.url} target="_blank" rel="noopener noreferrer">Open {tool.name} ↗</a>:<button className="secondary" disabled>Not configured</button>}<p className="muted">External tools retain their own sign-in. This entry does not monitor live availability or grant additional permissions.</p></section>
}
