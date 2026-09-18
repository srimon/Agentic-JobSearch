/**
 * The left panel of the Bagala standard shell, as data (17 Sep 2026): every selectable entry of this product, in the
 * order and with the groups the public site and the Products page use, so `npm run test:charts` (node --test tests/)
 * can check what each role is offered without a browser. SidePanel.tsx renders what this returns.
 *
 * Two contexts (18 Sep 2026). On the workspace views the groups are: the product's own group (Job Search: the
 * workspace entries by role), Products (Relax > Ask about a Book; Job > Job Search, Interview Preparation),
 * Documentation, Admin (administrators only) and Account. On an admin view (ADMIN_VIEWS: the console, observability,
 * the daily workflow, activity and every data view) the page wears the hub's standard groups without a product group
 * and Job Search is no longer marked current: the same panel the public site and the Library reader show, so choosing
 * Admin console from another product no longer lands in Job Search's product navigation.
 *
 * The Admin group is platform/brand/panel.json's, entry for entry and in its order (app/panel.json is the
 * byte-identical copy; tests/panel.test.mjs compares both): the entries on this product's public address become
 * in-app views, the Library reader's pages follow the session's library link, Slack stays a link. 'Data management'
 * is the folded sub-group: closed until pressed, open on its own views, closed again when another entry is chosen.
 * Each group has one dark accent; each entry an icon drawn in code (Icons.tsx) and one calm motion.
 */
export const SITE = 'https://www.bagala.ai';
/** The one place the product names the site: the header and the page title carry these words. */
export const SITE_TITLE = 'Deep Learning Agents';
export const PRODUCT = 'Job Search';
/** The header's product line on an admin view. */
export const ADMIN = 'Admin';
/** The public addresses panel.json names: an entry on one of them is rebased onto the address in use. */
export const PUBLIC = {jobs: 'https://bagala.ai/jobsearch/', library: 'https://bagala.ai/library/reader', prep: 'https://bagala.ai/jobprep/'};
/** The calm motions the site gives its icons (bagala.css .option__icon--* rules). */
export const MOTIONS = ['pulse', 'sway', 'spin', 'nudge', 'bounce', 'orbit', 'wiggle'];
/** The accents a group may carry (shell.css .side__group--* rules). */
export const ACCENTS = ['product', 'start', 'relax', 'jobs', 'docs', 'tools', 'account', 'data'];

const entry = (id, label, icon, motion, extra = {}) => ({id, label, icon, motion, ...extra});
const trailing = (url) => (url.endsWith('/') ? url : url + '/');

/**
 * The standard groups, as platform/brand/panel.json gives them on 17 Sep 2026: labels and addresses verbatim, in its
 * order; the icons and motions are this product's. `sub` nests a labelled sub-group inside an entry; the sub-group
 * whose id is 'data' is the fold.
 */
export const STANDARD = {
  products: {
    id: 'products', label: 'Products', accent: 'start',
    sub: [
      {id: 'relax', label: 'Relax', entries: [{label: 'Ask about a Book', href: PUBLIC.library, icon: 'book', motion: 'sway'}]},
      {id: 'jobs', label: 'Job', entries: [
        {label: 'Job Search', href: PUBLIC.jobs, icon: 'search', motion: 'orbit'},
        {label: 'Interview Preparation', href: PUBLIC.prep, icon: 'chat', motion: 'pulse'},
      ]},
    ],
  },
  docs: {
    id: 'docs', label: 'Documentation', accent: 'docs',
    entries: [
      {label: 'Overview', href: SITE + '/docs', icon: 'document', motion: 'sway'},
      {label: 'Create Account', href: SITE + '/docs/create-account', icon: 'signin', motion: 'wiggle'},
      {label: 'Ask the Book', href: SITE + '/docs/read-books', icon: 'book', motion: 'sway'},
      {label: 'Job Search', href: SITE + '/docs/job-search', icon: 'search', motion: 'orbit'},
      {label: 'Training', href: SITE + '/docs/interview-preparation', icon: 'chat', motion: 'pulse'},
      {label: 'Help and troubleshooting', href: SITE + '/help', icon: 'help', motion: 'pulse'},
      {label: 'Resources', href: SITE + '/#resources', icon: 'code', motion: 'nudge'},
    ],
  },
  admin: {
    id: 'admin', label: 'Admin', accent: 'tools', roles: ['administrator'],
    entries: [
      {label: 'Admin console', href: PUBLIC.jobs + '?view=admin', icon: 'gauge', motion: 'pulse'},
      {label: 'Observability – Job Search', href: PUBLIC.jobs + '?view=observability', icon: 'chart', motion: 'bounce'},
      {label: 'Observability – Ask about a Book', href: PUBLIC.library + '/observability', icon: 'book', motion: 'sway'},
      {label: 'Explain', href: PUBLIC.library + '/explain', icon: 'help', motion: 'pulse'},
      {label: 'VectorDB', href: PUBLIC.library + '/vectordb', icon: 'layers', motion: 'orbit'},
      {label: 'Library operations', href: PUBLIC.library + '/operations', icon: 'sliders', motion: 'sway'},
      {label: 'Daily workflow', href: PUBLIC.jobs + '?view=workflow', icon: 'clock', motion: 'sway'},
      {label: 'Agents and activity', href: PUBLIC.jobs + '?view=runs', icon: 'orbit', motion: 'spin'},
      {label: 'Data management', icon: 'database', motion: 'nudge', sub: [
        {id: 'data', label: 'Data management', accent: 'data', entries: [
          {label: 'ClickHouse', href: PUBLIC.jobs + '?view=data-clickhouse', icon: 'database', motion: 'nudge'},
          {label: 'Great Expectations', href: PUBLIC.jobs + '?view=data-gx', icon: 'shield', motion: 'pulse'},
          {label: 'SODA', href: PUBLIC.jobs + '?view=data-soda', icon: 'check', motion: 'pulse'},
          {label: 'PostgreSQL · SchemaSpy', href: PUBLIC.jobs + '?view=model', icon: 'document', motion: 'sway'},
          {label: 'OpenMetadata · Catalog', href: PUBLIC.jobs + '?view=data-catalog', icon: 'book', motion: 'sway'},
          {label: 'OpenMetadata', href: PUBLIC.jobs + '?view=data-governance', icon: 'shield', motion: 'wiggle'},
          {label: 'OpenMetadata · Lineage', href: PUBLIC.jobs + '?view=data-lineage', icon: 'chart', motion: 'bounce'},
          {label: 'ML feature dataset', href: PUBLIC.jobs + '?view=data-science', icon: 'orbit', motion: 'orbit'},
          {label: 'ClickHouse ingestion', href: PUBLIC.jobs + '?view=data-ingestion', icon: 'upload', motion: 'bounce'},
          {label: 'dbt Core', href: PUBLIC.jobs + '?view=data-dbt', icon: 'code', motion: 'nudge'},
        ]},
      ]},
      {label: 'Slack', href: 'https://app.slack.com/client/T0BG19JLPF1/C0BGLC0055J', icon: 'chat', motion: 'pulse'},
    ],
  },
  account: {
    id: 'account', label: 'Account', accent: 'account',
    entries: [
      {label: 'Sign in', href: 'https://bagala.ai/account/', icon: 'signin', motion: 'wiggle'},
      {label: 'Protected Account', href: SITE + '/#trust', icon: 'lock', motion: 'wiggle'},
      {label: 'Email Admin', action: 'enquiry', icon: 'mail', motion: 'bounce'},
    ],
  },
};

/** The view an address on this product's public address names (`?view=...`), or null for any other address. */
export function viewOf(href) {
  if (typeof href !== 'string' || !href.startsWith(PUBLIC.jobs)) return null;
  const match = /[?&]view=([a-z][a-z0-9-]*)/.exec(href);
  return match ? match[1] : null;
}

const foldOf = (group) => group.entries.find((item) => item.sub && item.sub[0] && item.sub[0].id === 'data').sub[0];

/** The views of the folded Data management sub-group ('model' among them), plus the Slack notifications view. */
export const DATA_VIEWS = [...foldOf(STANDARD.admin).entries.map((item) => viewOf(item.href)), 'data-slack'];

/**
 * The admin context: the views the hub's Admin group opens here (the console, observability, the daily workflow,
 * activity, every data view including Slack notifications). On these the page wears the standard groups without a
 * product group, the header reads 'Admin', and the pane takes the Admin accent.
 */
export const ADMIN_VIEWS = [...new Set([...STANDARD.admin.entries.map((item) => viewOf(item.href)).filter(Boolean), ...DATA_VIEWS])];

export const isAdminView = (view) => typeof view === 'string' && (ADMIN_VIEWS.includes(view) || view.startsWith('data-'));
/** True when the Data management fold opens by itself: on one of its own views. */
export const isDataView = (view) => typeof view === 'string' && (DATA_VIEWS.includes(view) || view.startsWith('data-'));

/** The workspace entries of the product's own group, by role. The console views now live in the Admin group. */
export function workspaceEntries({member = false, admin = false} = {}) {
  return [
    entry('matches', 'Opportunities', 'search', 'orbit'),
    entry('saved', 'Saved jobs', 'bookmark', 'sway'),
    entry('emailed', 'Emailed jobs', 'mail', 'bounce'),
    entry('archive', 'Archive', 'archive', 'wiggle'),
    ...(member ? [entry('intake', 'Resume & profile', 'upload', 'bounce'), entry('applications', 'Application checks', 'check', 'pulse')] : []),
    ...(admin ? [entry('review', 'Needs review', 'shield', 'pulse'), entry('sources', 'Sources', 'database', 'nudge')] : []),
  ].map((item) => ({...item, view: item.id}));
}

const slug = (label) => label.toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '');

/**
 * One of panel.json's entries on the address in use: a `?view=` on this product becomes the in-app view of that
 * name; a Library reader page follows the session's library link (the public address when the session gives none);
 * anything else stays the link it is. A sub-group whose id is 'data' becomes the fold, its entries localised the same way.
 */
export function localizeEntry(item, links = {}) {
  const view = viewOf(item.href);
  if (view) return entry(view, item.label, item.icon, item.motion, {view});
  if (item.sub) {
    const group = item.sub[0];
    return entry(group.id, item.label, item.icon, item.motion, {fold: true, accent: group.accent || 'data', entries: group.entries.map((child) => localizeEntry(child, links))});
  }
  if (typeof item.href === 'string' && item.href.startsWith(PUBLIC.library)) {
    const path = item.href.slice(PUBLIC.library.length);
    const href = links.library ? trailing(links.library) + path.replace(/^\/+/, '') : item.href;
    return entry('library' + path.replace(/\//g, '-'), item.label, item.icon, item.motion, {href, external: true});
  }
  return entry(slug(item.label), item.label, item.icon, item.motion, {href: item.href, external: true});
}

/**
 * The whole panel for one visitor.
 *
 * @param {object} context
 * @param {{name:string,roles:string[]}|null} context.user the signed-in account, or null
 * @param {{hub?:string,library?:string,prep?:string,governance?:string,clickhouse?:string}} context.links the other products' addresses from the session
 * @param {string} context.own this product's own address (the sign-in landing on the prefix in use)
 * @param {string} context.signIn where Sign in goes when nobody is signed in (the hub's account screen, or this page)
 * @param {string} context.tab the view on screen: an admin view (ADMIN_VIEWS) puts the panel in the admin context
 */
export function panelGroups({user = null, links = {}, own = '/', signIn = '/', tab = 'matches'} = {}) {
  const roles = Array.isArray(user?.roles) ? user.roles : [];
  const admin = roles.includes('administrator');
  const member = admin || roles.includes('member');
  const adminContext = isAdminView(tab);
  const groups = [];

  if (!adminContext) groups.push({id: 'product', label: PRODUCT, accent: 'product', entries: workspaceEntries({member, admin}), subgroups: []});

  groups.push({
    id: 'products', label: 'Products', accent: 'start',
    entries: [entry('hub', 'Products', 'grid', 'orbit', {href: links.hub || SITE + '/#products', external: !!links.hub})],
    subgroups: [
      {id: 'relax', label: 'Relax', accent: 'relax', entries: [entry('library', 'Ask about a Book', 'book', 'sway', {href: links.library || SITE + '/docs/read-books', external: !!links.library})]},
      {id: 'jobs', label: 'Job', accent: 'jobs', entries: [
        entry('jobsearch', 'Job Search', 'search', 'orbit', {href: own, current: !adminContext}),
        entry('prep', 'Interview Preparation', 'chat', 'pulse', {href: links.prep || SITE + '/docs/interview-preparation', external: !!links.prep}),
      ]},
    ],
  });

  groups.push({
    id: 'docs', label: 'Documentation', accent: 'docs', subgroups: [],
    entries: STANDARD.docs.entries.map((item) => entry('docs-' + slug(item.label), item.label, item.icon, item.motion, {href: item.href})),
  });

  if (admin) groups.push({id: 'admin', label: STANDARD.admin.label, accent: STANDARD.admin.accent, entries: STANDARD.admin.entries.map((item) => localizeEntry(item, links)), subgroups: []});

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

/** Every entry of every group, sub-group and fold, flattened, for tests and for the view lookup. */
export function allEntries(groups) {
  const out = [];
  const walk = (entries) => {
    for (const item of entries) {
      out.push(item);
      if (item.fold) walk(item.entries || []);
    }
  };
  for (const group of groups) {
    walk(group.entries);
    for (const sub of group.subgroups || []) {
      if (sub.entries) walk(sub.entries);
      for (const section of sub.sections || []) walk(section.entries);
    }
  }
  return out;
}

/** The pane's group for a chosen view: which accent its eyebrow and headings take, and what the eyebrow says. */
export function viewGroup(view) {
  if (view === 'account') return 'account';
  if (isAdminView(view)) return 'admin';
  return 'product';
}

export const GROUP_LABELS = {product: PRODUCT, admin: ADMIN, account: 'Account'};
