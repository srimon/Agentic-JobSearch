/**
 * The left panel of the standard shell (app/panel.mjs), checked by role and by context: what a visitor, a member
 * and an administrator are offered on a workspace view and on an admin view, in the site's order, each entry with
 * an icon that exists and a calm motion, each group with its accent; and that the Admin group is the hub's
 * platform/brand/panel.json, entry for entry (app/panel.json is the byte-identical copy). `npm run test:charts`
 * runs every test in this directory.
 */
import {strict as assert} from 'node:assert';
import {existsSync, readFileSync} from 'node:fs';
import test from 'node:test';
import {ACCENTS, ADMIN, ADMIN_VIEWS, DATA_VIEWS, GROUP_LABELS, MOTIONS, PRODUCT, PUBLIC, SITE, SITE_TITLE, STANDARD, allEntries, isAdminView, isDataView, localizeEntry, panelGroups, viewGroup, viewOf, workspaceEntries} from '../app/panel.mjs';

const links = {hub: 'https://hub.bagala.ai/', library: 'https://bagala.ai/library/reader', prep: 'https://bagala.ai/jobprep/', governance: 'https://governance.example/', clickhouse: 'https://clickhouse.example/'};
const ROOT = {name: 'Root', roles: ['administrator']};
const visitor = (tab) => panelGroups({user: null, links, own: '/jobsearch/', signIn: 'https://bagala.ai/account/?next=x', tab});
const member = (tab) => panelGroups({user: {name: 'Ada', roles: ['member']}, links, own: '/jobsearch/', signIn: '/jobsearch/', tab});
const admin = (tab) => panelGroups({user: ROOT, links, own: '/jobsearch/', signIn: '/jobsearch/', tab});
const labels = (group) => group.entries.map((e) => e.label);
const byId = (groups, id) => groups.find((g) => g.id === id);
const fold = (groups) => byId(groups, 'admin').entries.find((e) => e.fold);
/** The icons Icons.tsx draws, read from its IconName union so the test needs no TypeScript. */
const ICONS = (() => {
  const source = readFileSync(new URL('../app/Icons.tsx', import.meta.url), 'utf8');
  const union = /export type IconName=([^;]+);/.exec(source);
  assert.ok(union, 'Icons.tsx names its icons in an IconName union');
  return union[1].split('|').map((name) => name.trim().replace(/^'|'$/g, ''));
})();
const copy = JSON.parse(readFileSync(new URL('../app/panel.json', import.meta.url), 'utf8'));

test('the shell names the site the way the public site does, and never says Enterprise', () => {
  assert.equal(SITE_TITLE, 'Deep Learning Agents');
  assert.equal(PRODUCT, 'Job Search');
  assert.equal(ADMIN, 'Admin');
  assert.equal(SITE, 'https://www.bagala.ai');
  for (const groups of [visitor(), member(), admin(), admin('admin')]) {
    for (const item of allEntries(groups)) assert.doesNotMatch(item.label, /enterprise/i, item.id);
    for (const group of groups) assert.doesNotMatch(group.label, /enterprise/i, group.id);
  }
});

test('on a workspace view the groups come in the standard order: the product first, then Products, User creation, Documentation, Admin for administrators, Account last', () => {
  for (const tab of ['matches', 'saved', 'emailed', 'archive', 'intake', 'applications', 'review', 'sources', 'account', undefined]) {
    assert.deepEqual(visitor(tab).map((g) => g.id), ['product', 'products', 'signup', 'docs', 'account'], String(tab));
    assert.deepEqual(member(tab).map((g) => g.id), ['product', 'products', 'signup', 'docs', 'account'], String(tab));
    assert.deepEqual(admin(tab).map((g) => g.id), ['product', 'products', 'signup', 'docs', 'admin', 'account'], String(tab));
  }
  for (const groups of [visitor(), member(), admin()]) {
    assert.equal(groups[0].label, 'Job Search');
    assert.equal(groups[groups.length - 1].label, 'Account');
  }
});

test('the admin context: on an admin view there is no product group, and Job Search is no longer marked current', () => {
  assert.deepEqual(ADMIN_VIEWS, ['admin', 'observability', 'workflow', 'runs', 'data-clickhouse', 'data-gx', 'data-soda', 'model',
    'data-catalog', 'data-governance', 'data-lineage', 'data-science', 'data-ingestion', 'data-dbt', 'data-slack']);
  for (const tab of ADMIN_VIEWS) {
    assert.ok(isAdminView(tab), tab);
    assert.deepEqual(admin(tab).map((g) => g.id), ['products', 'signup', 'docs', 'admin', 'account'], tab);
    assert.equal(byId(admin(tab), 'products').subgroups[0].entries[0].current, false, tab);
    assert.equal(byId(admin(tab), 'products').subgroups[0].entries[0].href, '/jobsearch/', tab);
    // a member or a visitor who lands on an admin address gets the standard groups too (page.tsx sends a member back to Opportunities)
    assert.deepEqual(member(tab).map((g) => g.id), ['products', 'signup', 'docs', 'account'], tab);
    assert.deepEqual(visitor(tab).map((g) => g.id), ['products', 'signup', 'docs', 'account'], tab);
  }
  assert.ok(isAdminView('data-anything'), 'every data view is an admin view');
  for (const tab of ['matches', 'saved', 'emailed', 'archive', 'intake', 'applications', 'review', 'sources', 'account', 'quality', 'governance']) {
    assert.equal(isAdminView(tab), false, tab);
    assert.equal(byId(admin(tab), 'products').subgroups[0].entries[0].current, true, tab);
  }
  assert.equal(isAdminView(undefined), false);
});

test('the product group holds the workspace entries by role: four for a visitor, six for a member, eight for an administrator; the console views live in Admin', () => {
  assert.deepEqual(labels(byId(visitor(), 'product')), ['Opportunities', 'Saved jobs', 'Emailed jobs', 'Archive']);
  assert.deepEqual(labels(byId(member(), 'product')), ['Opportunities', 'Saved jobs', 'Emailed jobs', 'Archive', 'Resume & profile', 'Application checks']);
  assert.deepEqual(labels(byId(admin(), 'product')), ['Opportunities', 'Saved jobs', 'Emailed jobs', 'Archive', 'Resume & profile', 'Application checks', 'Needs review', 'Sources']);
  // every workspace entry switches the pane to the view of the same name, and none is a link away from the product
  for (const item of byId(admin(), 'product').entries) {
    assert.equal(item.view, item.id);
    assert.equal(item.href, undefined);
    assert.ok(!isAdminView(item.view), item.id + ' belongs to the workspace, not the admin context');
  }
  assert.equal(workspaceEntries({member: true, admin: true}).length, 8);
  for (const groups of [visitor(), member(), admin()]) assert.deepEqual(byId(groups, 'product').subgroups, [], 'no sub-group under the product any more');
});

test('Products leads with Choose a product, then Job > Job Search (this product) and Interview Preparation, then Relax > Ask about a Book', () => {
  for (const groups of [visitor(), member(), admin()]) {
    const products = byId(groups, 'products');
    assert.equal(products.accent, 'start');
    assert.deepEqual(products.entries.map((e) => [e.label, e.href]), [['Choose a product', links.hub]]);
    // the owner's order of 18 Sep 2026: Job before Relax
    assert.deepEqual(products.subgroups.map((s) => [s.label, s.accent]), [['Job', 'jobs'], ['Relax', 'relax']]);
    assert.deepEqual(products.subgroups[0].entries.map((e) => [e.label, e.href, !!e.current]),
      [['Job Search', '/jobsearch/', true], ['Interview Preparation', links.prep, false]]);
    assert.deepEqual(products.subgroups[1].entries.map((e) => [e.label, e.href]), [['Ask about a Book', links.library]]);
  }
  // without the session's links the entries go to the site's own pages for the products
  const bare = byId(panelGroups({user: null, links: {}}), 'products');
  assert.equal(bare.entries[0].href, SITE + '/#choose-a-product');
  assert.equal(bare.subgroups[0].entries[1].href, SITE + '/docs/interview-preparation');
  assert.equal(bare.subgroups[1].entries[0].href, SITE + '/docs/read-books');
});

test('User creation comes straight after Products, for everyone: the account step and the guide moved out of Documentation', () => {
  for (const groups of [visitor(), member(), admin(), admin('admin')]) {
    const ids = groups.map((g) => g.id);
    assert.equal(ids[ids.indexOf('products') + 1], 'signup');
    const signup = byId(groups, 'signup');
    assert.equal(signup.label, 'User creation');
    assert.equal(signup.accent, 'signup');
    assert.deepEqual(signup.entries.map((e) => [e.id, e.label, e.href]), [
      ['signup-create-your-account', 'Create your account', SITE + '/#create-your-account'],
      ['signup-create-account', 'Create Account', SITE + '/docs/create-account'],
    ]);
    assert.deepEqual(signup.subgroups, []);
  }
});

test('Documentation lists the site\'s six guides in its order, on the public site; Create Account has left it', () => {
  const docs = byId(visitor(), 'docs');
  assert.equal(docs.accent, 'docs');
  assert.deepEqual(labels(docs), ['Overview', 'Ask the Book', 'Job Search', 'Training', 'Help and troubleshooting', 'Resources']);
  assert.deepEqual(docs.entries.map((e) => e.href), [SITE + '/docs', SITE + '/docs/read-books', SITE + '/docs/job-search',
    SITE + '/docs/interview-preparation', SITE + '/help', SITE + '/#resources']);
});

test('Admin is for administrators only, in both contexts, and is the hub\'s Admin group entry for entry: in-app views here, links to the Library reader, Slack', () => {
  assert.equal(byId(visitor(), 'admin'), undefined);
  assert.equal(byId(member(), 'admin'), undefined);
  assert.equal(byId(member('admin'), 'admin'), undefined);
  for (const tab of ['matches', 'admin', 'data-gx', 'model']) {
    const group = byId(admin(tab), 'admin');
    assert.equal(group.label, 'Admin');
    assert.equal(group.accent, 'tools');
    assert.deepEqual(labels(group), STANDARD.admin.entries.map((e) => e.label), tab);
    assert.deepEqual(group.entries.map((e) => e.view || e.href || e.action || (e.fold ? 'fold' : null)), [
      'admin', 'observability',
      links.library + '/observability', links.library + '/explain', links.library + '/vectordb', links.library + '/operations', links.library + '/book-queue',
      'workflow', 'runs', 'fold', 'https://app.slack.com/client/T0BG19JLPF1/C0BGLC0055J', 'page-text',
    ], tab);
    // every in-app entry carries its view as its id (so aria-current can be set from the tab); the links leave the product
    for (const item of group.entries) {
      if (item.view) { assert.equal(item.id, item.view); assert.equal(item.href, undefined); }
      else if (!item.fold && !item.action) assert.equal(item.external, true, item.id);
    }
    // 'Edit the text on this page' is a control this page provides, not an address: it turns on in-place editing.
    const edit = group.entries[group.entries.length - 1];
    assert.deepEqual([edit.id, edit.label, edit.action, edit.href, edit.view], ['page-text', 'Edit the text on this page', 'page-text', undefined, undefined]);
  }
  // the Library reader's pages follow the session's library link, wherever it is; without one they keep the public address
  const local = byId(panelGroups({user: ROOT, links: {library: 'http://localhost:3001/reader/'}}), 'admin');
  assert.equal(local.entries.find((e) => e.label === 'Explain').href, 'http://localhost:3001/reader/explain');
  // the book queue (the crawler's approvals, 18 Sep 2026) is a Library reader page right after Library operations
  const queue = local.entries.find((e) => e.label === 'Book queue');
  assert.equal(queue.href, 'http://localhost:3001/reader/book-queue');
  assert.equal(queue.id, 'library-book-queue');
  assert.equal(queue.external, true);
  assert.equal(queue.view, undefined, 'the queue is the reader\'s page, not a view of this product');
  assert.equal(labels(local).indexOf('Book queue'), labels(local).indexOf('Library operations') + 1);
  const bare = byId(panelGroups({user: ROOT, links: {}}), 'admin');
  assert.equal(bare.entries.find((e) => e.label === 'VectorDB').href, PUBLIC.library + '/vectordb');
  assert.equal(bare.entries.length, STANDARD.admin.entries.length, 'nothing is dropped when the session gives no links');
  assert.equal(viewOf(PUBLIC.jobs + '?view=data-gx'), 'data-gx');
  assert.equal(viewOf(PUBLIC.library + '/explain'), null);
  assert.equal(viewOf('https://jobs.example/?view=admin'), null, 'only this product\'s public address names a view');
});

test('Data management is the fold: ten in-app entries in the hub\'s order under the data accent, open on its own views and closed elsewhere', () => {
  const data = fold(admin());
  assert.equal(data.id, 'data');
  assert.equal(data.label, 'Data management');
  assert.equal(data.accent, 'data');
  assert.equal(data.fold, true);
  assert.equal(data.entries.length, 10);
  assert.deepEqual(data.entries.map((e) => e.label), ['ClickHouse', 'Great Expectations', 'SODA', 'PostgreSQL · SchemaSpy', 'OpenMetadata · Catalog',
    'OpenMetadata', 'OpenMetadata · Lineage', 'ML feature dataset', 'ClickHouse ingestion', 'dbt Core']);
  assert.deepEqual(data.entries.map((e) => e.view), ['data-clickhouse', 'data-gx', 'data-soda', 'model', 'data-catalog', 'data-governance',
    'data-lineage', 'data-science', 'data-ingestion', 'data-dbt']);
  for (const item of data.entries) { assert.equal(item.id, item.view); assert.equal(item.href, undefined); }
  // the fold's position: between Agents and activity and Slack, as the public site renders it
  const order = labels(byId(admin(), 'admin'));
  assert.equal(order.indexOf('Data management'), order.indexOf('Agents and activity') + 1);
  assert.equal(order.indexOf('Slack'), order.indexOf('Data management') + 1);
  // open by itself on its own views (and Slack notifications), closed on every other
  assert.deepEqual(DATA_VIEWS, [...data.entries.map((e) => e.view), 'data-slack']);
  for (const view of DATA_VIEWS) assert.ok(isDataView(view), view);
  for (const view of ['admin', 'observability', 'workflow', 'runs', 'matches', 'account', undefined]) assert.equal(isDataView(view), false, String(view));
  // every data view names a tool of data-management.ts (SchemaSpy is the 'model' tool), so no entry leads to an empty pane
  const tools = [...readFileSync(new URL('../app/data-management.ts', import.meta.url), 'utf8').matchAll(/"id":\s*"([a-z]+)"/g)].map((m) => m[1]);
  for (const item of data.entries) assert.ok(tools.includes(item.view.replace(/^data-/, '')), item.view + ' is a data-management tool');
});

test('Account carries the name, the account screen and Sign out when signed in; Sign in to the given address when not; Email Admin always', () => {
  const out = byId(visitor(), 'account');
  assert.equal(out.accent, 'account');
  assert.equal(out.name, null);
  assert.deepEqual(out.entries.map((e) => [e.label, e.href || e.action]), [['Sign in', 'https://bagala.ai/account/?next=x'], ['Email Admin', 'enquiry']]);
  const inside = byId(member(), 'account');
  assert.equal(inside.name, 'Ada');
  assert.deepEqual(inside.entries.map((e) => [e.label, e.view || e.action]), [['Account', 'account'], ['Sign out', 'signout'], ['Email Admin', 'enquiry']]);
  assert.equal(byId(admin(), 'account').name, 'Root');
  assert.equal(byId(admin('admin'), 'account').name, 'Root');
});

test('every entry carries a code-drawn icon that Icons.tsx has and one of the site\'s calm motions; every group, sub-group and fold an accent of the shell', () => {
  assert.ok(ICONS.length > 20, ICONS.length + ' icons');
  for (const groups of [visitor(), member(), admin(), admin('admin'), admin('data-gx')]) {
    const seen = new Set();
    for (const group of groups) {
      assert.ok(ACCENTS.includes(group.accent), group.id);
      for (const sub of group.subgroups) assert.ok(ACCENTS.includes(sub.accent), sub.id);
    }
    for (const item of allEntries(groups)) {
      assert.ok(ICONS.includes(item.icon), item.id + ': icon ' + item.icon);
      assert.ok(MOTIONS.includes(item.motion), item.id + ': ' + item.motion);
      assert.ok(item.view || item.href || item.action || item.fold, item.id + ' leads nowhere');
      if (item.fold) assert.ok(ACCENTS.includes(item.accent), item.id);
      assert.ok(!seen.has(item.id), 'duplicate ' + item.id);
      seen.add(item.id);
    }
  }
  for (const item of STANDARD.admin.entries.flatMap((e) => (e.sub ? [e, ...e.sub[0].entries] : [e]))) assert.ok(ICONS.includes(item.icon), item.label + ': icon ' + item.icon);
  assert.deepEqual(MOTIONS, ['pulse', 'sway', 'spin', 'nudge', 'bounce', 'orbit', 'wiggle']);
});

test('the pane takes the accent of the group its screen belongs to: the product on the workspace, Admin on every admin and data view', () => {
  for (const view of ['matches', 'saved', 'emailed', 'archive', 'intake', 'applications', 'review', 'sources', 'quality', 'governance']) {
    assert.equal(viewGroup(view), 'product', view);
  }
  assert.equal(viewGroup('account'), 'account');
  for (const view of ADMIN_VIEWS) assert.equal(viewGroup(view), 'admin', view);
  assert.deepEqual(GROUP_LABELS, {product: 'Job Search', admin: 'Admin', account: 'Account'});
});

test('the standard groups agree with app/panel.json, the copy of the hub\'s panel.json, entry for entry', () => {
  const group = (id) => copy.groups.find((g) => g.id === id);
  const flat = (entries) => entries.map((e) => (e.sub ? {label: e.label, sub: e.sub.map((s) => ({id: s.id, label: s.label, entries: flat(s.entries)}))} : {label: e.label, href: e.href, action: e.action}));
  assert.equal(copy.title, SITE_TITLE);
  assert.deepEqual(flat(STANDARD.admin.entries), flat(group('admin').entries));
  assert.deepEqual(STANDARD.admin.roles, group('admin').roles);
  assert.deepEqual(flat(STANDARD.docs.entries), flat(group('docs').entries));
  assert.deepEqual(flat(STANDARD.signup.entries), flat(group('signup').entries));
  assert.equal(STANDARD.signup.label, group('signup').label);
  assert.deepEqual(flat(STANDARD.account.entries), flat(group('account').entries));
  // the sub-groups hang under 'Choose a product' now, and the hub's Products group is labelled Products
  assert.equal(group('start').label, 'Products');
  const products = group('start').entries.find((e) => e.label === 'Choose a product');
  assert.deepEqual(STANDARD.products.sub.map((s) => ({id: s.id, label: s.label, entries: flat(s.entries)})),
    products.sub.map((s) => ({id: s.id, label: s.label, entries: flat(s.entries)})));
  // the two removed steps are gone from the copy, so nothing here can bring them back
  const everyLabel = copy.groups.flatMap((g) => g.entries.map((e) => e.label));
  for (const gone of ['Use it with your own data', 'Keep improving']) assert.equal(everyLabel.includes(gone), false, gone);
  assert.equal(copy.pageText, '/__hub/page-text');
  // the panel renders exactly these: the localised Admin group and the copy have the same labels in the same order
  const rendered = byId(admin(), 'admin').entries.flatMap((e) => (e.fold ? [e.label, ...e.entries.map((c) => c.label)] : [e.label]));
  const written = group('admin').entries.flatMap((e) => (e.sub ? [e.label, ...e.sub[0].entries.map((c) => c.label)] : [e.label]));
  assert.deepEqual(rendered, written);
  assert.ok(copy.notes.some((note) => /folded/.test(note)), 'the copy carries the hub\'s note on the fold');
  assert.equal(localizeEntry(group('admin').entries[0], links).view, 'admin');
});

test('app/panel.json is byte-identical to the hub\'s platform/brand/panel.json when that file is beside this checkout', (t) => {
  // apps/jobsearch/frontend/tests -> the hub root, four levels up.
  const file = new URL('../../../../platform/brand/panel.json', import.meta.url);
  if (!existsSync(file)) {
    t.skip('the hub\'s platform/brand/panel.json is not beside this checkout');
    return;
  }
  assert.equal(readFileSync(new URL('../app/panel.json', import.meta.url), 'utf8'), readFileSync(file, 'utf8'));
});

test('nothing wrong paints before hydration: the page names no product, no group and no screen until the address\'s ?view= has been read', () => {
  const page = readFileSync(new URL('../app/page.tsx', import.meta.url), 'utf8');
  assert.match(page, /const \[viewReady,setViewReady\]=useState\(false\)/, 'viewReady starts false on the server and the client alike');
  assert.doesNotMatch(page, /useState\([^)]*typeof window/, 'no initial state reads the window: that would mismatch on hydration');
  const effect = page.split('\n').find((line) => line.includes("params.get('view')") && line.includes('setTab('));
  assert.ok(effect, 'the mount effect that reads ?view=');
  assert.match(effect, /^ useEffect\(\(\)=>\{const params=new URLSearchParams\(window\.location\.search\);/);
  assert.match(effect, /\}setViewReady\(true\)\},\[\]\);\s*$/, 'the same effect declares the view ready, last, after the tab is set');
  assert.equal((page.match(/setViewReady\(true\)/g) || []).length, 1, 'and nothing else does');
  assert.match(page, /<BrandHeader group=\{viewReady\?group:null\} product=\{viewReady\?\(groupLabel==='Account'\?PRODUCT:groupLabel\):null\}\/>/, 'the header carries a product line, and the group whose colour it takes, only once the view is known');
  assert.match(page, /<SidePanel [^>]*viewReady=\{viewReady\}/, 'the panel is told');
  assert.match(page, /className="page-heading page-arrival">\{viewReady\?<div><div className=\{'eyebrow eyebrow--'\+group\}>\{groupLabel\}<\/div><h1 data-text=\{'jobsearch\.'\+tab\+'\.heading'\}>\{labels\[tab\]\}<\/h1>/, 'the pane\'s eyebrow and heading wait');
  assert.match(page, /\{viewReady&&\['matches','emailed'\]\.includes\(tab\)&&<SearchOverview/, 'so does the search overview');
  const panel = readFileSync(new URL('../app/SidePanel.tsx', import.meta.url), 'utf8');
  assert.match(panel, /const groups=\(viewReady\?panelGroups\(\{user:user\|\|null,links,own,signIn,tab\}\):\[\]\) as Group\[\]/, 'the panel is an empty shell until then');
  const brand = readFileSync(new URL('../app/Brand.tsx', import.meta.url), 'utf8');
  assert.match(brand, /\{product\?<span className="site-header__product">\{product\}<\/span>:null\}/, 'no product, no product line');
  assert.doesNotMatch(brand, /product=PRODUCT/, 'the header no longer assumes Job Search');
  // the guards that send a member or a visitor away from an admin view are untouched
  assert.match(page, /if\(user&&!admin&&\(adminOnly\.includes\(tab\)\|\|tab\.startsWith\('data-'\)\)\)choose\('matches'\)/);
  assert.match(page, /!admin&&adminOnly\.includes\(tab\)\?<div className="message">Administrator access is required\.<\/div>/);
});

test('inside the Admin pane, Observability\'s eyebrow says Admin in the admin accent, and its heading names the product it observes', () => {
  const source = readFileSync(new URL('../app/Observability.tsx', import.meta.url), 'utf8');
  assert.match(source, /<span className="eyebrow eyebrow--admin">Admin<\/span>/);
  assert.doesNotMatch(source, /eyebrow--product/);
  assert.match(source, /<h2>\{tool==='phoenix'\?'Explainability':'Observability'\} · Job Search<\/h2>/);
  // the admin eyebrow is the tools accent's darker heading shade wherever it appears, in the shell and in the pane
  assert.match(readFileSync(new URL('../app/shell.css', import.meta.url), 'utf8'), /\.eyebrow--admin\{color:var\(--accent-tools-strong\)\}/);
  assert.match(readFileSync(new URL('../app/visual-theme.css', import.meta.url), 'utf8'), /\.pane \.eyebrow--admin,\.pane \.eyebrow--tools\{color:var\(--accent-tools-strong\)\}/);
});
