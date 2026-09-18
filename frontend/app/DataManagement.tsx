 'use client';
import {slackChannelUrl} from './slack-link';
import {dataGroups} from './data-management';
import {MotionIcon,type IconName} from './Icons';
import DataQuality from './DataQuality';
import Analytics from './Analytics';
import DataModel from './DataModel';
import Governance from './Governance';
/* The Data management entries themselves live in the left panel (panel.mjs, SidePanel.tsx: the folded sub-group of the Admin group, for administrators). */
const heroIcons:Record<string,IconName>={clickhouse:'database',gx:'shield',soda:'shield',model:'document',catalog:'book',governance:'shield',lineage:'chart',science:'orbit',ingestion:'upload',dbt:'code',dag:'clock'};
export default function DataManagement({tab,version}:{tab:string;version:number}){
 const id=tab.replace('data-','');const tool=dataGroups.flatMap(g=>g.tools).find(t=>t.id===id);
 // Each tool opens its own focused view; the shared screens show only the chosen tool's part.
 if(id==='gx'||id==='soda'||id==='dbt')return <DataQuality key={id} version={version} initialEngine={id} focused/>;
 if(id==='clickhouse'||id==='science'||id==='ingestion')return <Analytics key={id} version={version} view={id}/>;
 if(id==='model')return <DataModel version={version}/>;
 if(id==='governance'||id==='catalog'||id==='lineage')return <Governance key={id} view={id}/>;
 if(id==='slack')return <section className="dq"><div className="dq-hero"><MotionIcon name="chat" motion="pulse"/><div><span className="eyebrow eyebrow--data">Notifications</span><h2>Slack</h2><p>Sean · #general · the hub&rsquo;s Slack app</p></div></div><p>The Slack connection is configured for Hub notifications. This page does not poll delivery status.</p>{!slackChannelUrl&&<p>The channel’s browser link has not been supplied yet.</p>}<a className="primary" href={slackChannelUrl||'https://app.slack.com/client'} target="_blank" rel="noopener noreferrer">{slackChannelUrl?'Open #general':'Open Slack'} ↗</a><p className="muted">Sign in with your Slack account. Webhook credentials are never included in this page.</p></section>;
 if(!tool)return <p>Select a data management tool in the panel.</p>;
 return <section className="dq"><div className="dq-hero"><MotionIcon name={heroIcons[tool.id]||'code'} motion="pulse"/><div><span className="eyebrow eyebrow--data">Data management</span><h2>{tool.name}</h2><p>{tool.description}</p></div></div><p><strong>{tool.status}</strong></p>{tool.url?<a className="primary" href={tool.url} target="_blank" rel="noopener noreferrer">Open {tool.name} ↗</a>:<button className="secondary" disabled>Not configured</button>}<p className="muted">External tools retain their own sign-in. This entry does not monitor live availability or grant additional permissions.</p></section>
}
