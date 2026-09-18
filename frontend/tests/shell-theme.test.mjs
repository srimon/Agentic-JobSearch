/**
 * The look of the standard shell in this product (app/shell.css, globals.css, visual-theme.css), 18 September 2026:
 *
 * - every group's heading takes its own darker shade (--accent-<group>-strong) through --group-label, and each of
 *   those shades is at least 7:1 on the gold grounds the panel, the page and the chosen entry use;
 * - about a third less vertical space: the line height, the panel's paddings and the card and section paddings;
 * - a finger still gets 44 px in the panel on a phone;
 * - the movable divider is a separator with the clamp, the key and the default the hub's shell.js uses.
 */
import {strict as assert} from 'node:assert';
import {readFileSync} from 'node:fs';
import test from 'node:test';

const read = (name) => readFileSync(new URL('../app/' + name, import.meta.url), 'utf8');
const shell = read('shell.css'), globals = read('globals.css'), theme = read('visual-theme.css');
const sidePanel = readFileSync(new URL('../app/SidePanel.tsx', import.meta.url), 'utf8');

/** The value of a custom property declared in shell.css, following one level of var() indirection. */
function token(name) {
  const found = new RegExp('--' + name + ':\\s*([^;}]+)').exec(shell);
  assert.ok(found, '--' + name + ' is declared');
  return found[1].trim();
}

const channel = (value) => (value <= 0.03928 ? value / 12.92 : Math.pow((value + 0.055) / 1.055, 2.4));
function luminance(hex) {
  const parts = /^#([0-9a-f]{2})([0-9a-f]{2})([0-9a-f]{2})$/i.exec(hex);
  assert.ok(parts, hex + ' is a six-digit hex colour');
  const [r, g, b] = parts.slice(1).map((part) => channel(parseInt(part, 16) / 255));
  return 0.2126 * r + 0.7152 * g + 0.0722 * b;
}
function contrast(a, b) {
  const [high, low] = [luminance(a), luminance(b)].sort((x, y) => y - x);
  return (high + 0.05) / (low + 0.05);
}

/* The grounds a group's heading is ever set on: the page, the panel, and the chosen entry's honey. */
const GROUNDS = {'gold-300': '#F5E4A8', 'gold-400': '#EED58A', 'gold-500': '#E4C463'};
const GROUPS = ['start', 'signup', 'relax', 'jobs', 'docs', 'account', 'tools', 'data', 'page', 'product'];

test('every group has a heading shade of its own, darker than its entries and at least 7:1 on every gold ground', () => {
  for (const group of GROUPS) {
    const entry = token('accent-' + group), heading = token('accent-' + group + '-strong');
    assert.match(heading, /^#[0-9A-Fa-f]{6}$/, group);
    assert.ok(luminance(heading) < luminance(entry), group + ': the heading shade is darker than the entries');
    for (const [name, ground] of Object.entries(GROUNDS)) {
      const ratio = contrast(heading, ground);
      assert.ok(ratio >= 7, group + '-strong on ' + name + ' is ' + ratio.toFixed(2) + ':1');
    }
  }
  assert.equal(new Set(GROUPS.map((group) => token('accent-' + group + '-strong'))).size, GROUPS.length, 'no two groups share a heading shade');
});

test('the labels take the heading shade, not the entries\' colour: the panel, the sub-groups, the header\'s product line and the eyebrow', () => {
  assert.match(shell, /\.side__label\{[^}]*color:var\(--group-label\)/);
  assert.match(shell, /\.side__sublabel\{[^}]*color:var\(--group-label\)/);
  assert.match(shell, /\.site-header__product\{[^}]*color:var\(--group-label\)/);
  // the header is told which group the screen belongs to, so 'Job Search' and 'Administrator' read as headings
  for (const group of ['product', 'admin', 'account']) assert.match(shell, new RegExp('\\.site-header\\[data-group="' + group + '"\\]\\{--group-label:'));
  for (const group of [...GROUPS, 'admin']) assert.match(shell, new RegExp('\\.side__group--' + group + '\\{--group-accent:[^}]*--group-label:var\\(--accent-'), group);
  // the entries themselves keep the group's own accent
  assert.match(shell, /\.side__list a,\.side__button\{[^}]*color:var\(--group-accent\)/);
  // and the pane's eyebrow takes the heading shade too
  assert.match(theme, /\.pane \.eyebrow--product\{color:var\(--accent-product-strong\)\}/);
  assert.match(theme, /\.pane \.eyebrow--admin,\.pane \.eyebrow--tools\{color:var\(--accent-tools-strong\)\}/);
});

test('about a third less vertical space, and never below 44 px for a finger', () => {
  assert.match(globals, /body\{[^}]*line-height:1\.4\}/, 'the body line height is 1.4');
  assert.match(shell, /\.side__group\{padding:6px 0 8px/);
  assert.match(shell, /\.side__list\{[^}]*gap:1px\}/);
  assert.match(shell, /\.side__list a,\.side__button\{[^}]*padding:6px 12px/);
  assert.match(shell, /\.side__label\{[^}]*margin:0 12px 4px\}/);
  assert.match(shell, /\.side__nav\{[^}]*padding:12px 14px 20px\}/);
  assert.match(shell, /\.option\{[^}]*padding:12px;/, 'the option rows are 12px, not 18px');
  assert.match(globals, /\.job-card\{[^}]*padding:16px;/);
  assert.match(globals, /\.filters\{[^}]*padding:12px;/);
  assert.match(globals, /\.account-panel\{[^}]*padding:16px\}/);
  // a phone keeps the touch target, whatever the rhythm
  assert.match(shell, /\.side__list a,\.side__button,\.side__fold>summary\{min-height:44px\}/);
  assert.match(shell, /\.option\{[^}]*min-height:44px/);
  assert.match(globals, /@media\(max-width:700px\)\{\.filter-multi__choice\{min-height:44px\}\}/);
});

test('the divider is a separator between the panel and the pane, with the hub\'s clamp, key and default', () => {
  assert.match(sidePanel, /SIDE_KEY='bagala\.side',SIDE_MIN=200,SIDE_MAX=560,SIDE_DEFAULT=288/);
  assert.match(sidePanel, /role="separator"/);
  assert.match(sidePanel, /aria-orientation="vertical"/);
  assert.match(sidePanel, /aria-valuemin=\{SIDE_MIN\} aria-valuemax=\{SIDE_MAX\} aria-valuenow=\{now\}/);
  assert.match(sidePanel, /onMouseDown=\{grab\} onDoubleClick=\{restore\} onKeyDown=\{keys\}/);
  // the keys the owner asked for, and the width written where the stylesheet reads it
  for (const key of ["'ArrowLeft'", "'ArrowRight'", "'Home'", "'End'"]) assert.ok(sidePanel.includes(key), key);
  assert.match(sidePanel, /setProperty\('--side',next\+'px'\)/);
  assert.match(sidePanel, /localStorage\.setItem\(SIDE_KEY/);
  assert.match(sidePanel, /localStorage\.removeItem\(SIDE_KEY\)/);
  // it starts at the default on the server and the client alike: nothing is read from the window during a render
  assert.doesNotMatch(sidePanel, /useState\([^)]*localStorage/);
  // and it is gone where the panel is a drawer
  assert.match(shell, /\.shell\{[^}]*position:relative\}/);
  assert.match(shell, /\.side__resize\{position:absolute;top:0;left:var\(--side\)/);
  assert.match(shell, /@media \(max-width:900px\)\{[\s\S]*?\.side__resize\{display:none\}/);
});
