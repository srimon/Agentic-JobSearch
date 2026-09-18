/**
 * Chart shaping for the administrator console. Numbers in, geometry out: no DOM, no React and no
 * chart library, so every scale, tick and path can be checked on its own (tests/admin-charts.test.mjs,
 * `npm run test:charts`). The console draws plain <svg> from what these return.
 *
 * The awkward cases are the ones that matter on a console with very little traffic: a range with no
 * days in it, a range with exactly one day, and a series that is all zeroes. None of them may draw a
 * spike out of nowhere, divide by zero, or leave an empty box on the screen.
 *
 * @typedef {{key:string,label:string,values:number[],tone?:number,dashed?:boolean}} Series
 * @typedef {{width:number,height:number,left:number,right:number,top:number,bottom:number}} Box
 */

/**
 * The drawing area every line chart uses (compressed 18 Sep 2026: 140 high, from 210). The console measures each
 * card and draws with the card's own width in place of this one, so a chart is never scaled: its 13px labels stay
 * 13px whether the cards sit in one column or three. This width is the one drawn before the first measurement.
 */
export const CHART_BOX = {width: 360, height: 140, left: 50, right: 10, top: 10, bottom: 24};

/** The sparkline's box (180 by 36, from 220 by 46). */
export const SPARK_BOX = {width: 180, height: 36};

/**
 * How many series tones there are (admin-console.css .ac-tone1 to .ac-tone10): the group accents and the dark
 * inks, each at least 7:1 on the gold grounds, so a legend can be set in its series' colour.
 */
export const TONES = 10;

/** @param {number} value */
const round = (value) => Math.round(value * 1e6) / 1e6;
/** @param {unknown} value */
const finite = (value) => (typeof value === 'number' && Number.isFinite(value) ? value : Number.isFinite(Number(value)) ? Number(value) : 0);

/**
 * The tone (1 to TONES) for the n-th series, bar or segment of a chart, cycling so every row of a long list has a
 * colour and no two neighbours share one. Anything that is not a whole number counts as the first.
 * @param {number} index
 * @returns {number}
 */
export function tone(index) {
 const position = Math.max(0, Math.floor(finite(index)));
 return (position % TONES) + 1;
}

/**
 * Round a number up to a friendly step: 1, 2, 2.5, 5 or 10 times a power of ten. Never 0, so it is
 * always safe to divide by.
 * @param {number} value
 * @returns {number}
 */
export function niceCeil(value) {
 const size = finite(value);
 if (size <= 0) return 1;
 const power = Math.pow(10, Math.floor(Math.log10(size)));
 const scaled = size / power;
 const step = scaled <= 1 ? 1 : scaled <= 2 ? 2 : scaled <= 2.5 ? 2.5 : scaled <= 5 ? 5 : 10;
 return round(step * power);
}

/**
 * The axis: a friendly step, the top it reaches and the tick values in between. `integer` keeps the
 * step whole, which is what a count of people or requests needs.
 * @param {number} max
 * @param {{steps?:number,integer?:boolean}} [options]
 * @returns {{top:number,step:number,ticks:number[]}}
 */
export function axisScale(max, options = {}) {
 const steps = Math.max(1, Math.round(options.steps || 4));
 const size = finite(max);
 if (size <= 0) return {top: 1, step: 1, ticks: [0, 1]};
 let step = niceCeil(size / steps);
 if (options.integer) step = Math.max(1, Math.ceil(step));
 const ticks = [];
 for (let index = 0; index <= steps; index += 1) ticks.push(round(step * index));
 return {top: round(step * steps), step, ticks};
}

/**
 * The largest value in a set of series. Anything that is not a number counts as zero rather than
 * poisoning the scale with NaN.
 * @param {Series[]} series
 * @returns {number}
 */
export function seriesMax(series) {
 let most = 0;
 for (const item of series || []) for (const value of (item && item.values) || []) most = Math.max(most, finite(value));
 return most;
}

/**
 * Points, a line path and an area path for each series inside the box, plus the axis they share.
 * A single day is drawn flat across the width instead of as one dot in the middle of nothing, and an
 * empty series returns no path at all so the caller can show its own empty state.
 * @param {Series[]} series
 * @param {Box} [box]
 * @param {{max?:number,steps?:number,integer?:boolean}} [options]
 */
export function shapeSeries(series, box = CHART_BOX, options = {}) {
 const list = (series || []).filter(Boolean);
 const length = list.reduce((most, item) => Math.max(most, (item.values || []).length), 0);
 const scale = axisScale(options.max === undefined ? seriesMax(list) : options.max, options);
 const plotWidth = box.width - box.left - box.right;
 const plotHeight = box.height - box.top - box.bottom;
 const baseline = box.top + plotHeight;
 /** @param {number} index */
 const x = (index) => (length <= 1 ? round(box.left + plotWidth / 2) : round(box.left + (index / (length - 1)) * plotWidth));
 /** @param {number} value */
 const y = (value) => round(baseline - (Math.min(Math.max(finite(value), 0), scale.top) / scale.top) * plotHeight);
 const shaped = list.map((item) => {
  const values = (item.values || []).map(finite);
  const points = values.map((value, index) => ({index, value, x: x(index), y: y(value)}));
  const drawn = points.length === 1
   ? [{...points[0], x: box.left}, {...points[0], x: round(box.left + plotWidth)}]
   : points;
  const line = drawn.length ? 'M ' + drawn.map((point) => point.x + ' ' + point.y).join(' L ') : '';
  const area = drawn.length
   ? line + ' L ' + drawn[drawn.length - 1].x + ' ' + baseline + ' L ' + drawn[0].x + ' ' + baseline + ' Z'
   : '';
  return {...item, values, points, line, area};
 });
 return {length, baseline, plotWidth, plotHeight, box, top: scale.top, ticks: scale.ticks, series: shaped, x, y};
}

/**
 * Bars as a share of the widest row, each with its tone: the row's own when it names one (a host-keyed row keeps
 * the colour its line has in the day charts, so a product is one colour across the console), the cycling one
 * otherwise (an unordered list, where no two neighbours may share one). A row with nothing in it gets no bar rather
 * than a stub that looks like a small value.
 * @template {{value:number,tone?:number}} T
 * @param {T[]} rows
 * @returns {(T & {width:number,tone:number})[]}
 */
export function barRows(rows) {
 const list = rows || [];
 const most = list.reduce((top, row) => Math.max(top, finite(row && row.value)), 0);
 return list.map((row, index) => {
  const value = finite(row && row.value);
  const own = !!row && Number.isInteger(row.tone) && row.tone >= 1 && row.tone <= TONES;
  return {...row, value, tone: own ? row.tone : tone(index), width: most <= 0 || value <= 0 ? 0 : Math.max(1.5, round((value / most) * 100))};
 });
}

/**
 * One stacked bar: each part gets where it starts, how wide it is and its share of the whole, in
 * percent of the bar. An empty or all-zero stack reports total 0 and no width, so the caller shows
 * its empty state instead of a bar made of nothing.
 * @param {{key:string,label:string,value:number}[]} parts
 */
export function stackSegments(parts) {
 const list = (parts || []).map((part) => ({...part, value: Math.max(0, finite(part && part.value))}));
 const total = list.reduce((sum, part) => sum + part.value, 0);
 let start = 0;
 const segments = list.map((part) => {
  const width = total > 0 ? round((part.value / total) * 100) : 0;
  const segment = {...part, start: round(start), width, share: total > 0 ? round(part.value / total) : 0};
  start += width;
  return segment;
 });
 return {total, segments};
}

/**
 * A sparkline: the path, the last value, and the highest value it reached.
 * @param {number[]} values
 * @param {{width?:number,height?:number,pad?:number}} [box]
 */
export function sparkline(values, box = {}) {
 const width = box.width || SPARK_BOX.width;
 const height = box.height || SPARK_BOX.height;
 const pad = box.pad === undefined ? 3 : box.pad;
 const list = (values || []).map(finite);
 const top = Math.max(...list, 0) || 1;
 const plot = height - pad * 2;
 const x = (index) => (list.length <= 1 ? width : round((index / (list.length - 1)) * width));
 const y = (value) => round(height - pad - (Math.min(Math.max(value, 0), top) / top) * plot);
 const points = list.map((value, index) => ({index, value, x: list.length === 1 ? 0 : x(index), y: y(value)}));
 const drawn = points.length === 1 ? [{...points[0], x: 0}, {...points[0], x: width}] : points;
 return {
  path: drawn.length ? 'M ' + drawn.map((point) => point.x + ' ' + point.y).join(' L ') : '',
  points, top, width, height,
  current: list.length ? list[list.length - 1] : null,
 };
}

/**
 * Which x positions get a printed label, so they never collide on a narrow card: always the first
 * and the last, and evenly spaced ones in between.
 * @param {number} length
 * @param {number} [most]
 * @returns {number[]}
 */
export function labelIndexes(length, most = 5) {
 const count = Math.max(0, Math.floor(length));
 const wanted = Math.max(2, Math.floor(most));
 if (count <= 0) return [];
 if (count <= wanted) return Array.from({length: count}, (_, index) => index);
 const step = (count - 1) / (wanted - 1);
 const chosen = new Set();
 for (let index = 0; index < wanted; index += 1) chosen.add(Math.round(index * step));
 return [...chosen].sort((left, right) => left - right);
}

/**
 * The step-to-step conversion of a funnel, kept honest: a step wider than the one above it (more
 * sign-ups than visitors in the range, which the weekly visitor re-keying can produce) keeps its
 * real share and its real bar width rather than being clipped to look tidy.
 * @param {{step:string,value:number,of_previous:number|null}[]} steps
 */
export function funnelBars(steps) {
 const list = (steps || []).map((step) => ({...step, value: Math.max(0, finite(step && step.value))}));
 const widest = list.reduce((top, step) => Math.max(top, step.value), 0);
 return list.map((step, index) => ({
  ...step,
  width: widest > 0 && step.value > 0 ? Math.max(1.5, round((step.value / widest) * 100)) : 0,
  of_first: index === 0 || !list[0].value ? null : round(step.value / list[0].value),
 }));
}
