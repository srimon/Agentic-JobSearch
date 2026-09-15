import catalog from "./job-board-links.json";
export default function JobBoards(){
 const boards=catalog.boards;
 return <section className="collection-panel"><h2>Job-board integrations</h2><p>The public employer catalog also includes 55 Greenhouse and Ashby boards imported from Job Prep. Their enabled state and collection history appear in the source list below. These links are saved in the product’s versioned source directory.</p>{boards.map(b=><div key={b.name} className="collection-source"><strong>{b.name}</strong><span>{b.status}</span><small>{b.detail}</small><a href={b.url} target="_blank" rel="noopener noreferrer">Open {b.name} search ↗</a></div>)}</section>
}
