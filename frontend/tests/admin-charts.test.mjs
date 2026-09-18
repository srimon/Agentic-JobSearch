/**
 * The administrator console's chart shaping, on its own: `npm run test:charts` (node --test, no
 * test framework and no new dependency). These cover the cases a console with very little traffic
 * actually hits - an empty range, a single day, a series that is all zeroes - because each of them
 * used to be a way to draw a spike out of nothing or divide by zero.
 */
import test from 'node:test';
import assert from 'node:assert/strict';

import {readFileSync} from 'node:fs';

import {axisScale, barRows, CHART_BOX, funnelBars, labelIndexes, niceCeil, seriesMax, shapeSeries, SPARK_BOX, sparkline, stackSegments, TONES, tone} from '../app/admin-charts.mjs';

const days = (...values) => [{key: 'a', label: 'A', values}];

test('the chart box is the compressed one (18 Sep 2026): 140 high with a small top and bottom, and the spark 180 by 36', () => {
 assert.equal(CHART_BOX.height, 140);
 assert.ok(CHART_BOX.top <= 12 && CHART_BOX.bottom <= 26, 'small top and bottom');
 assert.ok(CHART_BOX.height - CHART_BOX.top - CHART_BOX.bottom >= 100, 'room for the plot');
 assert.deepEqual(SPARK_BOX, {width: 180, height: 36});
 const line = sparkline([1, 2]);
 assert.equal(line.width, 180);
 assert.equal(line.height, 36);
 // the console draws with the card's measured width in place of the default one, so any width must shape cleanly
 for (const width of [200, 233, 360, 470, 900]) {
  const shape = shapeSeries(days(1, 5, 3), {...CHART_BOX, width});
  assert.equal(shape.series[0].points[0].x, CHART_BOX.left, String(width));
  assert.equal(shape.series[0].points[2].x, width - CHART_BOX.right, String(width));
 }
});

test('ten tones cycle so every series, bar and segment has a colour, and every tone the console names exists in its stylesheet', () => {
 assert.equal(TONES, 10);
 assert.deepEqual([0, 1, 2, 9, 10, 11, 19, 20].map(tone), [1, 2, 3, 10, 1, 2, 10, 1]);
 assert.equal(tone(-1), 1);
 assert.equal(tone(NaN), 1);
 assert.equal(tone(2.7), 3);
 const css = readFileSync(new URL('../app/admin-console.css', import.meta.url), 'utf8');
 for (let index = 1; index <= TONES; index += 1) assert.match(css, new RegExp('\\.ac-tone' + index + '\\{--tone:var\\(--[a-z-]+\\)\\}'), 'tone ' + index);
 assert.match(css, /\.ac-tone-panel\{--tone:var\(--panel-accent/, 'a single series takes the panel accent');
 for (const accent of ['relax', 'jobs', 'account', 'start']) assert.match(css, new RegExp('\\.ac-panel--' + accent + '\\{--panel-accent:var\\(--accent-' + accent + '\\)\\}'), accent);
 // brand tokens only: no literal colour anywhere in the stylesheet
 assert.equal(css.match(/#[0-9a-fA-F]{3,8}\b/g), null, 'no literal colour');
 assert.equal(css.match(/\b(?:rgb|hsl)a?\(/g), null, 'no literal colour function');
});

test('a friendly ceiling is never zero and never below the value', () => {
 assert.equal(niceCeil(0), 1);
 assert.equal(niceCeil(-8), 1);
 assert.equal(niceCeil(NaN), 1);
 assert.equal(niceCeil(1), 1);
 assert.equal(niceCeil(4), 5);
 assert.equal(niceCeil(120), 200);
 assert.equal(niceCeil(0.3), 0.5);
 for (const value of [1, 3, 7, 41, 99, 632, 12345]) assert.ok(niceCeil(value) >= value, String(value));
});

test('the axis has whole steps for counts and reaches its top exactly', () => {
 const four = axisScale(4, {steps: 4, integer: true});
 assert.deepEqual(four.ticks, [0, 1, 2, 3, 4]);
 assert.equal(four.top, 4);
 const wide = axisScale(632, {steps: 4});
 assert.deepEqual(wide.ticks, [0, 200, 400, 600, 800]);
 assert.equal(wide.top, wide.ticks[wide.ticks.length - 1]);
 const one = axisScale(1, {steps: 4, integer: true});
 assert.ok(one.ticks.every(Number.isInteger), 'a count axis never asks for 0.25 of a person');
});

test('an empty or all-zero series gets an axis of its own rather than a division by zero', () => {
 for (const max of [0, -5, NaN, undefined]) {
  const scale = axisScale(max);
  assert.deepEqual(scale.ticks, [0, 1]);
  assert.equal(scale.top, 1);
 }
 assert.equal(seriesMax([]), 0);
 assert.equal(seriesMax(days(0, 0, 0)), 0);
 assert.equal(seriesMax([{key: 'a', label: 'A', values: [1, 9]}, {key: 'b', label: 'B', values: [12]}]), 12);
});

test('an empty set of series draws nothing at all', () => {
 const shape = shapeSeries([]);
 assert.equal(shape.length, 0);
 assert.deepEqual(shape.series, []);
 assert.equal(shape.top, 1);
 const empty = shapeSeries(days());
 assert.equal(empty.series[0].line, '');
 assert.equal(empty.series[0].area, '');
});

test('a single day is drawn flat across the whole width, not as a spike', () => {
 const shape = shapeSeries(days(12));
 const [series] = shape.series;
 assert.equal(series.points.length, 1);
 assert.ok(series.line.startsWith('M ' + CHART_BOX.left + ' '), series.line);
 const ends = series.line.split(' L ');
 assert.equal(ends.length, 2);
 assert.ok(ends[1].startsWith(String(CHART_BOX.width - CHART_BOX.right)), series.line);
 const [, firstY] = ends[0].split(' ').slice(1);
 assert.equal(firstY, ends[1].split(' ')[1], 'both ends sit at the same height');
});

test('an all-zero series sits on the baseline instead of filling the card', () => {
 const shape = shapeSeries(days(0, 0, 0, 0));
 assert.equal(shape.top, 1);
 for (const point of shape.series[0].points) assert.equal(point.y, shape.baseline);
 assert.ok(shape.series[0].area.endsWith('Z'));
});

test('values are placed between the baseline and the top of the box, and nothing escapes it', () => {
 const shape = shapeSeries([{key: 'a', label: 'A', values: [0, 50, 100]}], CHART_BOX, {integer: true});
 const [series] = shape.series;
 assert.equal(series.points[0].y, shape.baseline);
 assert.ok(series.points[2].y < series.points[1].y, 'a bigger value is higher up the card');
 for (const point of series.points) {
  assert.ok(point.y >= CHART_BOX.top && point.y <= shape.baseline, 'inside the box: ' + point.y);
  assert.ok(point.x >= CHART_BOX.left && point.x <= CHART_BOX.width - CHART_BOX.right, 'inside the box: ' + point.x);
 }
 // A value beyond the axis top (a stale max handed in) is held at the top, never drawn off the card.
 const clamped = shapeSeries(days(500), CHART_BOX, {max: 100});
 assert.ok(clamped.series[0].points[0].y >= CHART_BOX.top);
});

test('bars are a share of the widest row, and an empty row gets no bar', () => {
 const rows = barRows([{value: 10}, {value: 5}, {value: 0}]);
 assert.equal(rows[0].width, 100);
 assert.equal(rows[1].width, 50);
 assert.equal(rows[2].width, 0);
 assert.deepEqual(barRows([]), []);
 for (const row of barRows([{value: 0}, {value: 0}])) assert.equal(row.width, 0);
 assert.ok(barRows([{value: 1000}, {value: 1}])[1].width >= 1.5, 'a tiny value is still visible');
});

test('a stacked bar fills exactly its width, and an empty stack says it is empty', () => {
 const {total, segments} = stackSegments([{key: '2xx', label: '2xx', value: 3}, {key: '4xx', label: '4xx', value: 1}]);
 assert.equal(total, 4);
 assert.deepEqual(segments.map((part) => part.width), [75, 25]);
 assert.deepEqual(segments.map((part) => part.start), [0, 75]);
 assert.equal(segments[0].share, 0.75);
 const empty = stackSegments([{key: 'a', label: 'a', value: 0}]);
 assert.equal(empty.total, 0);
 assert.equal(empty.segments[0].width, 0);
 assert.equal(stackSegments([]).total, 0);
});

test('a sparkline reports its current value and survives one sample or none', () => {
 const line = sparkline([1, 2, 3]);
 assert.equal(line.current, 3);
 assert.ok(line.path.startsWith('M 0 '));
 const single = sparkline([7]);
 assert.equal(single.current, 7);
 assert.equal(single.points.length, 1);
 assert.equal(single.path.split(' L ').length, 2, 'one sample is a flat line, not a dot');
 const none = sparkline([]);
 assert.equal(none.path, '');
 assert.equal(none.current, null);
 const zeroes = sparkline([0, 0]);
 assert.equal(zeroes.top, 1);
 assert.ok(zeroes.path.length > 0);
});

test('x labels never collide and always keep the first and last day', () => {
 assert.deepEqual(labelIndexes(0), []);
 assert.deepEqual(labelIndexes(3), [0, 1, 2]);
 const many = labelIndexes(30, 5);
 assert.ok(many.length <= 5);
 assert.equal(many[0], 0);
 assert.equal(many[many.length - 1], 29);
});

test('a funnel keeps a step that is wider than the one above it', () => {
 const bars = funnelBars([
  {step: 'Product visitors', value: 3, of_previous: null},
  {step: 'Sign-ups', value: 4, of_previous: 4 / 3},
 ]);
 assert.equal(bars[1].width, 100, 'the widest step is the full bar, whichever step that is');
 assert.equal(bars[0].width, 75);
 assert.ok(bars[1].of_first > 1, 'more sign-ups than visitors is reported, not hidden');
 for (const bar of funnelBars([{step: 'a', value: 0, of_previous: null}, {step: 'b', value: 0, of_previous: 0}])) {
  assert.equal(bar.width, 0);
 }
 assert.deepEqual(funnelBars([]), []);
});

test('a bar keeps the tone its row names, so a host is one colour in the day lines and in its bars; rows without one cycle', () => {
 const rows = barRows([{value: 3, tone: 4}, {value: 2}, {value: 1, tone: 4}, {value: 5, tone: 0}, {value: 5, tone: TONES + 1}, {value: 5, tone: 2.5}, {value: 5, tone: '3'}]);
 assert.deepEqual(rows.map((row) => row.tone), [4, 2, 4, 4, 5, 6, 7], 'its own tone when whole and within the ten, the cycling one otherwise');
 assert.deepEqual(barRows([{value: 1}, {value: 1}, {value: 1}]).map((row) => row.tone), [1, 2, 3]);
 assert.deepEqual(barRows([{value: 1, tone: 1}, {value: 1, tone: 1}]).map((row) => row.tone), [1, 1], 'two rows may share a named tone: the host decides, not the position');
 for (const row of barRows(Array.from({length: TONES + 2}, () => ({value: 1})))) assert.ok(row.tone >= 1 && row.tone <= TONES);
 assert.deepEqual(barRows([]), []);
 // the console hands the host's tone to its host-keyed lists (Requests per product, Visitors per product) and draws
 // what barRows resolved; the same toneFor colours the host's line in Requests per day
 const source = readFileSync(new URL('../app/AdminConsole.tsx', import.meta.url), 'utf8');
 assert.match(source, /'ac-bar-fill ac-tone'\+row\.tone\+\(row\.muted/, 'Bars draws the resolved tone');
 assert.doesNotMatch(source, /ac-tone'\+tone\(order\)\+\(row\.muted/, 'never the position alone (the funnel, which no host keys, still cycles)');
 for (const [list, field] of [['perHost', 'by_host'], ['reach', 'reach']]) {
  assert.match(source, new RegExp('const ' + list + '=useMemo\\(\\(\\)=>\\(body\\.' + field + "\\|\\|\\[\\]\\)\\.map\\(row=>\\(\\{key:s\\(row,'host'\\),label:nameFor\\(s\\(row,'host'\\),products\\),tone:toneFor\\(s\\(row,'host'\\),products\\)"), list + ' keys its tone by host');
 }
 assert.match(source, /values:hostSeries\(rows,days,host,'human_hits'\),tone:toneFor\(host,products\)\}\)\)/, 'the Requests per day lines take the same tone');
 assert.match(source, /tone\?:number\}\[\];empty\?:React\.ReactNode;highlight\?:string\}/, 'a row may name its tone');
});

test('the cards sit three across only from 1500px, and a card is a size container that stacks its bar rows below 330px', () => {
 const css = readFileSync(new URL('../app/admin-console.css', import.meta.url), 'utf8');
 assert.match(css, /\.ac-cards\{[^}]*grid-template-columns:repeat\(2,minmax\(0,1fr\)\)/, 'two columns by default');
 assert.match(css, /@media\(min-width:1500px\)\{\.ac-cards\{grid-template-columns:repeat\(3,minmax\(0,1fr\)\)\}\}/, 'three from 1500px');
 assert.match(css, /@media\(max-width:900px\)\{\.ac-cards\{grid-template-columns:minmax\(0,1fr\)\}\}/, 'one to 900px');
 assert.doesNotMatch(css, /min-width:1200px/, 'the 1200px rule that left each card near 230px beside the panel is gone');
 assert.match(css, /\.ac-card\{[^}]*container-type:inline-size/, 'the card is a size container');
 assert.match(css, /\.ac-card-wide\{grid-column:1\/-1\}/, 'a wide card still spans every column');
 const narrow = /@container \(max-width:330px\)\{([^]*?)\n\}/.exec(css);
 assert.ok(narrow, 'a container rule for a narrow card');
 assert.match(narrow[1], /\.ac-bars li,\.ac-funnel-row\{grid-template-columns:minmax\(0,1fr\) auto;row-gap:3px\}/, 'label and value on one row');
 assert.match(narrow[1], /\.ac-bar-track\{grid-column:1 \/ -1\}/, 'the track on a row of its own');
 // the same stacked layout the phone breakpoint uses, so the two never disagree
 const phone = /@media\(max-width:760px\)\{([^]*?)\n\}/.exec(css);
 assert.ok(phone, 'the phone breakpoint');
 assert.match(phone[1], /\.ac-bars li,\.ac-funnel-row\{grid-template-columns:minmax\(0,1fr\) auto;row-gap:3px\}/);
 assert.match(phone[1], /\.ac-bar-track\{grid-column:1 \/ -1\}/);
 // and the three-column bar row the container rule replaces has no fixed minimum a narrow card cannot honour
 assert.match(css, /\.ac-bars li,\.ac-funnel-row\{display:grid;grid-template-columns:minmax\(0,9rem\) minmax\(48px,1fr\) auto/);
});

test('status is the tint and a hairline, never a coloured word: the pills, the warning line and the bad figure set their text in the block ink, 7:1 and better', () => {
 const css = readFileSync(new URL('../app/admin-console.css', import.meta.url), 'utf8');
 assert.match(css, /\.ac-pill\{[^}]*;color:var\(--ink-block\)\}/, 'a pill\'s word is in the block ink');
 assert.match(css, /\.ac-pill-ok\{background:var\(--tint\);border-color:var\(--ok\)\}/);
 assert.match(css, /\.ac-pill-bad\{background:var\(--error-bg\);border-color:var\(--danger\)\}/);
 assert.match(css, /\.ac-summary\.ac-warn\{[^}]*;color:var\(--ink-block\)\}/, 'the warning line keeps its tint and its left rule');
 assert.match(css, /\.ac-figures>div\.ac-bad\{background:var\(--error-bg\);border-color:var\(--danger\)\}/);
 assert.match(css, /\.ac-figures>div\.ac-bad strong\{color:var\(--ink-block\)\}/);
 // no declaration anywhere sets words in a semantic colour
 assert.doesNotMatch(css, /[{;]color:var\(--(?:ok|warn|danger|warn-ink|error-ink)\)/);
 // and the header's 7:1 claim holds by measurement: the block ink on every tint used here, from the brand tokens
 const tokens = {};
 for (const file of ['globals.css', 'shell.css']) {
  for (const [, name, hex] of readFileSync(new URL('../app/' + file, import.meta.url), 'utf8').matchAll(/--([a-z0-9-]+):\s*(#[0-9A-Fa-f]{6})\b/g)) tokens[name] ??= hex;
 }
 const luminance = (hex) => [1, 3, 5].map((at) => parseInt(hex.slice(at, at + 2), 16) / 255)
  .map((c) => (c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4))
  .reduce((sum, c, i) => sum + c * [0.2126, 0.7152, 0.0722][i], 0);
 const contrast = (ink, ground) => {
  assert.ok(tokens[ink] && tokens[ground], ink + ' and ' + ground + ' are brand tokens');
  const [hi, lo] = [luminance(tokens[ink]), luminance(tokens[ground])].sort((x, y) => y - x);
  return (hi + 0.05) / (lo + 0.05);
 };
 for (const tint of ['surface-2', 'error-bg', 'warn-bg']) assert.ok(contrast('ink-block', tint) >= 7, 'ink-block on ' + tint + ': ' + contrast('ink-block', tint).toFixed(2));
 // why the words are not in the status colours: none of them reaches 7:1 on its tint (--tint is --surface-2)
 for (const [ink, tint] of [['ok', 'surface-2'], ['danger', 'error-bg'], ['warn', 'warn-bg'], ['danger', 'surface-2']]) {
  assert.ok(contrast(ink, tint) < 7, ink + ' on ' + tint + ' is under 7:1, so it is a hairline and a tint, not a word');
 }
});
