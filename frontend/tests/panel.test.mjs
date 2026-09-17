/**
 * The left panel of the standard shell (app/panel.mjs), checked by role: what a visitor, a member and an
 * administrator are offered, in the site's order, each entry with an icon and a calm motion, each group with
 * its accent. `npm run test:charts` runs every test in this directory.
 */
import {strict as assert} from 'node:assert';
import test from 'node:test';
import {ACCENTS, MOTIONS, PRODUCT, SITE, SITE_TITLE, allEntries, dataEntries, panelGroups, viewGroup, workspaceEntries} from '../app/panel.mjs';

const links = {hub: 'https://hub.bagala.ai/', library: 'https://bagala.ai/library/reader', prep: 'https://bagala.ai/jobprep/', governance: 'https://governance.example/', clickhouse: 'https://clickhouse.example/'};
const tools = [{name: 'Data Quality', tools: [{id: 'gx', name: 'Great Expectations'}, {id: 'soda', name: 'SODA'}]}, {name: 'Data Engineering', tools: [{id: 'dbt', name: 'dbt Core'}]}];
const visitor = () => panelGroups({user: null, links, own: '/jobsearch/', signIn: 'https://bagala.ai/account/?next=x'});
const member = () => panelGroups({user: {name: 'Ada', roles: ['member']}, links, dataManagement: true, dataGroups: tools, own: '/jobsearch/', signIn: '/jobsearch/'});
const admin = () => panelGroups({user: {name: 'Root', roles: ['administrator']}, links, dataManagement: true, dataGroups: tools, own: '/jobsearch/', signIn: '/jobsearch/'});
const labels = (group) => group.entries.map((e) => e.label);
const byId = (groups, id) => groups.find((g) => g.id === id);

test('the shell names the site the way the public site does, and never says Enterprise', () => {
  assert.equal(SITE_TITLE, 'Deep Learning Agents');
  assert.equal(PRODUCT, 'Job Search');
  assert.equal(SITE, 'https://www.bagala.ai');
  for (const groups of [visitor(), member(), admin()]) {
    for (const item of allEntries(groups)) assert.doesNotMatch(item.label, /enterprise/i, item.id);
    for (const group of groups) assert.doesNotMatch(group.label, /enterprise/i, group.id);
  }
});

test('the groups come in the standard order: the product first, then Products, Documentation, Admin for administrators, Account last', () => {
  assert.deepEqual(visitor().map((g) => g.id), ['product', 'products', 'docs', 'account']);
  assert.deepEqual(member().map((g) => g.id), ['product', 'products', 'docs', 'account']);
  assert.deepEqual(admin().map((g) => g.id), ['product', 'products', 'docs', 'admin', 'account']);
  for (const groups of [visitor(), member(), admin()]) {
    assert.equal(groups[0].label, 'Job Search');
    assert.equal(groups[groups.length - 1].label, 'Account');
  }
});

test('the product group holds the workspace entries by role: four for a visitor, six for a member, twelve for an administrator', () => {
  assert.deepEqual(labels(byId(visitor(), 'product')), ['Opportunities', 'Saved jobs', 'Emailed jobs', 'Archive']);
  assert.deepEqual(labels(byId(member(), 'product')), ['Opportunities', 'Saved jobs', 'Emailed jobs', 'Archive', 'Resume & profile', 'Application checks']);
  assert.deepEqual(labels(byId(admin(), 'product')), ['Opportunities', 'Saved jobs', 'Emailed jobs', 'Archive', 'Resume & profile', 'Application checks',
    'Needs review', 'Daily workflow', 'Sources', 'Activity', 'Observability', 'Admin console']);
  // every workspace entry switches the pane to the view of the same name, and none is a link away from the product
  for (const item of byId(admin(), 'product').entries) {
    assert.equal(item.view, item.id);
    assert.equal(item.href, undefined);
  }
  assert.equal(workspaceEntries({member: true, admin: true}).length, 12);
});

test('Data management is a sub-group of the product group for administrators only, and only when it is enabled', () => {
  assert.deepEqual(byId(visitor(), 'product').subgroups, []);
  assert.deepEqual(byId(member(), 'product').subgroups, []);
  const [data] = byId(admin(), 'product').subgroups;
  assert.equal(data.label, 'Data management');
  assert.equal(data.accent, 'data');
  assert.deepEqual(data.sections.map((s) => s.label), ['Data Quality', 'Data Engineering', 'Notifications']);
  assert.deepEqual(data.sections.flatMap((s) => s.entries.map((e) => e.view)), ['data-gx', 'data-soda', 'data-dbt', 'data-slack']);
  const off = panelGroups({user: {name: 'Root', roles: ['administrator']}, links, dataManagement: false, dataGroups: tools});
  assert.deepEqual(byId(off, 'product').subgroups, []);
  assert.equal(dataEntries([]).length, 1, 'Slack stays even without data tools');
});

test('Products offers the site\'s groups: Relax > Ask about a Book and Job > Job Search (this product) and Interview Preparation', () => {
  for (const groups of [visitor(), member(), admin()]) {
    const products = byId(groups, 'products');
    assert.equal(products.accent, 'start');
    assert.deepEqual(products.entries.map((e) => [e.label, e.href]), [['Products', links.hub]]);
    assert.deepEqual(products.subgroups.map((s) => [s.label, s.accent]), [['Relax', 'relax'], ['Job', 'jobs']]);
    assert.deepEqual(products.subgroups[0].entries.map((e) => [e.label, e.href]), [['Ask about a Book', links.library]]);
    assert.deepEqual(products.subgroups[1].entries.map((e) => [e.label, e.href, !!e.current]),
      [['Job Search', '/jobsearch/', true], ['Interview Preparation', links.prep, false]]);
  }
  // without the session's links the entries go to the site's own pages for the products
  const bare = byId(panelGroups({user: null, links: {}}), 'products');
  assert.equal(bare.entries[0].href, SITE + '/#products');
  assert.equal(bare.subgroups[0].entries[0].href, SITE + '/docs/read-books');
  assert.equal(bare.subgroups[1].entries[1].href, SITE + '/docs/interview-preparation');
});

test('Documentation lists the site\'s seven guides in its order, on the public site', () => {
  const docs = byId(visitor(), 'docs');
  assert.equal(docs.accent, 'docs');
  assert.deepEqual(labels(docs), ['Overview', 'Create Account', 'Ask the Book', 'Job Search', 'Training', 'Help and troubleshooting', 'Resources']);
  assert.deepEqual(docs.entries.map((e) => e.href), [SITE + '/docs', SITE + '/docs/create-account', SITE + '/docs/read-books', SITE + '/docs/job-search',
    SITE + '/docs/interview-preparation', SITE + '/help', SITE + '/#resources']);
});

test('Admin is for administrators only and holds the console links across the products', () => {
  assert.equal(byId(visitor(), 'admin'), undefined);
  assert.equal(byId(member(), 'admin'), undefined);
  const consoles = byId(admin(), 'admin');
  assert.equal(consoles.accent, 'tools');
  assert.deepEqual(consoles.entries.map((e) => [e.label, e.href || e.view]), [
    ['Products page tools', links.hub],
    ['Ask about a Book · Monitoring', links.library + '/observability'],
    ['Governance · OpenMetadata', links.governance],
    ['ClickHouse console', links.clickhouse],
    ['Slack notifications', 'data-slack'],
    ['Access', links.hub + '?view=access'],
  ]);
  // a console whose address the session does not give is simply not offered
  const few = byId(panelGroups({user: {name: 'Root', roles: ['administrator']}, links: {}}), 'admin');
  assert.deepEqual(few.entries.map((e) => e.label), ['Slack notifications']);
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
});

test('every entry carries a code-drawn icon and one of the site\'s calm motions; every group and sub-group an accent of the shell', () => {
  for (const groups of [visitor(), member(), admin()]) {
    const seen = new Set();
    for (const group of groups) {
      assert.ok(ACCENTS.includes(group.accent), group.id);
      for (const sub of group.subgroups) assert.ok(ACCENTS.includes(sub.accent), sub.id);
    }
    for (const item of allEntries(groups)) {
      assert.equal(typeof item.icon, 'string', item.id);
      assert.ok(item.icon.length > 0, item.id);
      assert.ok(MOTIONS.includes(item.motion), item.id + ': ' + item.motion);
      assert.ok(item.view || item.href || item.action, item.id + ' leads nowhere');
      assert.ok(!seen.has(item.id) || item.id === 'data-slack', 'duplicate ' + item.id);
      seen.add(item.id);
    }
  }
  assert.deepEqual(MOTIONS, ['pulse', 'sway', 'spin', 'nudge', 'bounce', 'orbit', 'wiggle']);
});

test('the pane takes the accent of the group its screen belongs to', () => {
  for (const view of ['matches', 'saved', 'emailed', 'archive', 'intake', 'applications', 'review', 'workflow', 'sources', 'runs', 'observability', 'admin']) {
    assert.equal(viewGroup(view), 'product', view);
  }
  assert.equal(viewGroup('account'), 'account');
  for (const view of ['data-gx', 'data-slack', 'data-clickhouse']) assert.equal(viewGroup(view), 'data', view);
});
