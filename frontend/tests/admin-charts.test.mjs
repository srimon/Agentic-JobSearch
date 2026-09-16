/**
 * The administrator console's chart shaping, on its own: `npm run test:charts` (node --test, no
 * test framework and no new dependency). These cover the cases a console with very little traffic
 * actually hits - an empty range, a single day, a series that is all zeroes - because each of them
 * used to be a way to draw a spike out of nothing or divide by zero.
 */
import test from 'node:test';
import assert from 'node:assert/strict';

import {axisScale, barRows, CHART_BOX, funnelBars, labelIndexes, niceCeil, seriesMax, shapeSeries, sparkline, stackSegments} from '../app/admin-charts.mjs';

const days = (...values) => [{key: 'a', label: 'A', values}];

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
