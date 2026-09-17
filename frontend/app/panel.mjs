/**
 * The left panel of the Bagala standard shell, as data (17 Sep 2026): every selectable entry of this product, in the
 * order and with the groups the public site and the Products page use, so `npm run test:charts` (node --test tests/)
 * can check what each role is offered without a browser. SidePanel.tsx renders what this returns.
 *
 * Groups, top to bottom: the product's own group (Job Search: the workspace entries by role, and Data management as
 * a sub-group for administrators), Products (Relax > Ask about a Book; Job > Job Search, Interview Preparation),
 * Documentation, Admin (administrators only: the console links across the products) and Account (the name, the
 * account screen and Sign out; or Sign in; then Email Admin). Each group has one dark accent; each entry an icon
 * drawn in code (Icons.tsx) and one calm motion. Until the hub publishes platform/brand/panel.json the standard
 * groups are the public site's (platform/gateway/welcome/index.html).
 */
export const SITE = 'https://www.bagala.ai';
/** The one place the product names the site: the header and the page title carry these words. */
export const SITE_TITLE = 'Deep Learning Agents';
export const PRODUCT = 'Job Search';
/** The calm motions the site gives its icons (bagala.css .option__icon--* rules). */
export const MOTIONS = ['pulse', 'sway', 'spin', 'nudge', 'bounce', 'orbit', 'wiggle'];
/** The accents a group may carry (shell.css .side__group--* rules). */
export const ACCENTS = ['product', 'start', 'relax', 'jobs', 'docs', 'tools', 'account', 'data'];

const entry = (id, label, icon, motion, extra = {}) => ({id, label, icon, motion, ...extra});
const trailing = (url) => (url.endsWith('/') ? url : url + '/');

/** The workspace entries of the product's own group, by role (the same rule page.tsx used for its sidebar). */
export function workspaceEntries({member = false, admin = false} = {}) {
  return [
    entry('matches', 'Opportunities', 'search', 'orbit'),
    entry('saved', 'Saved jobs', 'bookmark', 'sway'),
    entry('emailed', 'Emailed jobs', 'mail', 'bounce'),
    entry('archive', 'Archive', 'archive', 'wiggle'),
    ...(member ? [entry('intake', 'Resume & profile', 'upload', 'bounce'), entry('applications', 'Application checks', 'check', 'pulse')] : []),
    ...(admin ? [
      entry('review', 'Needs review', 'shield', 'pulse'),
      entry('workflow', 'Daily workflow', 'clock', 'sway'),
      entry('sources', 'Sources', 'database', 'nudge'),
      entry('runs', 'Activity', 'chart', 'bounce'),
      entry('observability', 'Observability', 'gauge', 'wiggle'),
      entry('admin', 'Admin console', 'orbit', 'spin'),
    ] : []),
  ].map((item) => ({...item, view: item.id}));
}

/** Data management: every tool of data-management.ts under its group, then Slack, as in-app views (administrators). */
export function dataEntries(dataGroups = []) {
  const icons = {clickhouse: 'database', gx: 'shield', soda: 'shield', model: 'document', catalog: 'book', governance: 'shield', lineage: 'chart', science: 'orbit', ingestion: 'upload', dbt: 'code', dag: 'clock'};
  const motions = ['pulse', 'sway', 'nudge', 'bounce', 'orbit', 'wiggle', 'spin'];
  const sections = dataGroups.map((group, index) => ({
    label: group.name,
    entries: group.tools.map((tool, position) => entry('data-' + tool.id, tool.name, icons[tool.id] || 'code', motions[(index + position) % motions.length], {view: 'data-' + tool.id})),
  }));
  sections.push({label: 'Notifications', entries: [entry('data-slack', 'Slack — #general', 'chat', 'pulse', {view: 'data-slack'})]});
  return sections;
}

/**
 * The whole panel for one visitor.
 *
 * @param {object} context
 * @param {{name:string,roles:string[]}|null} context.user the signed-in account, or null
 * @param {{hub?:string,library?:string,prep?:string,governance?:string,clickhouse?:string}} context.links the other products' addresses from the session
 * @param {boolean} context.dataManagement whether the data tools are enabled for this deployment
 * @param {Array<{name:string,tools:Array<{id:string,name:string}>}>} context.dataGroups the data tools (data-management.ts)
 * @param {string} context.own this product's own address (the sign-in landing on the prefix in use)
 * @param {string} context.signIn where Sign in goes when nobody is signed in (the hub's account screen, or this page)
 */
export function panelGroups({user = null, links = {}, dataManagement = false, dataGroups = [], own = '/', signIn = '/'} = {}) {
  const roles = Array.isArray(user?.roles) ? user.roles : [];
  const admin = roles.includes('administrator');
  const member = admin || roles.includes('member');
  const groups = [];

  const product = {id: 'product', label: PRODUCT, accent: 'product', entries: workspaceEntries({member, admin}), subgroups: []};
  if (admin && dataManagement) product.subgroups.push({id: 'data', label: 'Data management', accent: 'data', sections: dataEntries(dataGroups)});
  groups.push(product);

  groups.push({
    id: 'products', label: 'Products', accent: 'start',
    entries: [entry('hub', 'Products', 'grid', 'orbit', {href: links.hub || SITE + '/#products', external: !!links.hub})],
    subgroups: [
      {id: 'relax', label: 'Relax', accent: 'relax', entries: [entry('library', 'Ask about a Book', 'book', 'sway', {href: links.library || SITE + '/docs/read-books', external: !!links.library})]},
      {id: 'jobs', label: 'Job', accent: 'jobs', entries: [
        entry('jobsearch', 'Job Search', 'search', 'orbit', {href: own, current: true}),
        entry('prep', 'Interview Preparation', 'chat', 'pulse', {href: links.prep || SITE + '/docs/interview-preparation', external: !!links.prep}),
      ]},
    ],
  });

  groups.push({
    id: 'docs', label: 'Documentation', accent: 'docs', subgroups: [],
    entries: [
      entry('docs-overview', 'Overview', 'document', 'sway', {href: SITE + '/docs'}),
      entry('docs-create-account', 'Create Account', 'signin', 'wiggle', {href: SITE + '/docs/create-account'}),
      entry('docs-read-books', 'Ask the Book', 'book', 'sway', {href: SITE + '/docs/read-books'}),
      entry('docs-job-search', 'Job Search', 'search', 'orbit', {href: SITE + '/docs/job-search'}),
      entry('docs-training', 'Training', 'chat', 'pulse', {href: SITE + '/docs/interview-preparation'}),
      entry('docs-help', 'Help and troubleshooting', 'help', 'pulse', {href: SITE + '/help'}),
      entry('docs-resources', 'Resources', 'code', 'nudge', {href: SITE + '/#resources'}),
    ],
  });

  if (admin) {
    const consoles = [];
    if (links.hub) consoles.push(entry('hub-tools', 'Products page tools', 'grid', 'orbit', {href: links.hub, external: true}));
    if (links.library) consoles.push(entry('library-monitoring', 'Ask about a Book · Monitoring', 'chart', 'bounce', {href: trailing(links.library) + 'observability', external: true}));
    if (links.governance) consoles.push(entry('governance', 'Governance · OpenMetadata', 'shield', 'pulse', {href: links.governance, external: true}));
    if (links.clickhouse) consoles.push(entry('clickhouse', 'ClickHouse console', 'database', 'nudge', {href: links.clickhouse, external: true}));
    consoles.push(entry('data-slack', 'Slack notifications', 'chat', 'pulse', {view: 'data-slack'}));
    if (links.hub) consoles.push(entry('access', 'Access', 'lock', 'wiggle', {href: trailing(links.hub) + '?view=access', external: true}));
    groups.push({id: 'admin', label: 'Admin', accent: 'tools', entries: consoles, subgroups: []});
  }

  const account = {id: 'account', label: 'Account', accent: 'account', name: user?.name || null, subgroups: [], entries: []};
  if (user) {
    account.entries.push(entry('account', 'Account', 'signin', 'wiggle', {view: 'account'}));
    account.entries.push(entry('signout', 'Sign out', 'signout', 'nudge', {action: 'signout'}));
  } else {
    account.entries.push(entry('signin', 'Sign in', 'signin', 'wiggle', {href: signIn}));
  }
  account.entries.push(entry('enquiry', 'Email Admin', 'mail', 'bounce', {action: 'enquiry'}));
  groups.push(account);

  return groups;
}

/** Every entry of every group, sub-group and section, flattened, for tests and for the view lookup. */
export function allEntries(groups) {
  const out = [];
  for (const group of groups) {
    out.push(...group.entries);
    for (const sub of group.subgroups || []) {
      if (sub.entries) out.push(...sub.entries);
      for (const section of sub.sections || []) out.push(...section.entries);
    }
  }
  return out;
}

/** The pane's group for a chosen view: which accent its eyebrow and headings take. */
export function viewGroup(view) {
  if (view === 'account') return 'account';
  if (typeof view === 'string' && view.startsWith('data-')) return 'data';
  return 'product';
}
