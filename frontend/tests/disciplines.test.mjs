/**
 * The Discipline filter's words (app/disciplines.mjs): the owner's ten in the owner's order, what each one matches
 * in a listing's title and description, and the boundaries the matching keeps. `npm run test:charts` runs this.
 *
 * The same ten with the same keywords live in src/applications/disciplines.py, which builds the PostgreSQL pattern
 * /api/jobs?discipline= filters with; tests/test_disciplines.py there reads this module and refuses a difference.
 */
import {strict as assert} from 'node:assert';
import {readFileSync} from 'node:fs';
import test from 'node:test';
import {DISCIPLINES, DISCIPLINE_IDS, disciplineLabel, disciplinesFor, listingMatches, matchesDiscipline, normalize} from '../app/disciplines.mjs';

test('the ten disciplines are the owner\'s, in the owner\'s order', () => {
  assert.deepEqual(DISCIPLINES.map((item) => item.label), [
    'Software Engineering', 'AI Engineering', 'Data Engineering', 'Data Governance', 'Data Ingestion',
    'Data loading', 'Data lineage', 'Data Quality', 'Technical Program Management', 'Technical Project Management']);
  assert.deepEqual(DISCIPLINE_IDS, ['software-engineering', 'ai-engineering', 'data-engineering', 'data-governance',
    'data-ingestion', 'data-loading', 'data-lineage', 'data-quality', 'technical-program-management',
    'technical-project-management']);
  assert.equal(disciplineLabel('data-lineage'), 'Data lineage');
  assert.equal(disciplineLabel('nothing'), 'nothing');
  for (const item of DISCIPLINES) {
    assert.match(item.id, /^[a-z][a-z0-9-]*$/, item.id);
    assert.ok(item.keywords.length >= 5, item.id + ' has ' + item.keywords.length + ' keywords');
    for (const keyword of item.keywords) assert.match(keyword, /^[a-z0-9]+( [a-z0-9]+)*$/, item.id + ': ' + keyword);
  }
  assert.equal(new Set(DISCIPLINE_IDS).size, 10, 'no id twice');
});

test('the data is plain JSON, so src/applications/disciplines.py can read it out of this file', () => {
  const source = readFileSync(new URL('../app/disciplines.mjs', import.meta.url), 'utf8');
  const literal = /export const DISCIPLINES = (\[[\s\S]*?\n\]);/.exec(source);
  assert.ok(literal, 'the literal is written so it can be parsed');
  assert.deepEqual(JSON.parse(literal[1]), DISCIPLINES);
});

test('a title names its discipline, whatever its case or punctuation', () => {
  assert.ok(matchesDiscipline('software-engineering', 'Director, Software Engineering'));
  assert.ok(matchesDiscipline('software-engineering', 'SENIOR SOFTWARE ENGINEER'));
  assert.ok(matchesDiscipline('software-engineering', 'Staff Software Engineers, Platform'));
  assert.ok(matchesDiscipline('ai-engineering', 'Head of AI Engineering'));
  assert.ok(matchesDiscipline('ai-engineering', 'Machine Learning Engineer, GenAI'));
  assert.ok(matchesDiscipline('data-engineering', 'VP, Data Engineering'));
  assert.ok(matchesDiscipline('data-engineering', 'Director — Snowflake / dbt'));
  assert.ok(matchesDiscipline('data-governance', 'Director, Data Governance & Compliance'));
  assert.ok(matchesDiscipline('data-ingestion', 'Lead, Change Data Capture'));
  assert.ok(matchesDiscipline('data-loading', 'Engineer, Bulk Load Pipelines'));
  assert.ok(matchesDiscipline('data-lineage', 'Data Lineage Architect'));
  assert.ok(matchesDiscipline('data-quality', 'Manager, Data Quality'));
  assert.ok(matchesDiscipline('technical-program-management', 'Senior Technical Program Manager'));
  assert.ok(matchesDiscipline('technical-project-management', 'Technical Project Manager, Platform'));
  assert.equal(matchesDiscipline('not-a-discipline', 'anything at all'), false);
});

test('the matching is word-boundary aware: "data lineage" is not "lineage-free", and a word inside another word is not a match', () => {
  assert.equal(matchesDiscipline('data-lineage', 'A lineage-free tooling stack'), false);
  assert.equal(matchesDiscipline('data-lineage', 'lineage'), false, 'the keyword is the phrase, never the bare noun');
  assert.ok(matchesDiscipline('data-lineage', 'We own data-lineage end to end'), 'a hyphen inside the phrase still reads as the phrase');
  assert.ok(matchesDiscipline('data-lineage', 'Data / Lineage across the warehouse'));
  // a keyword that happens to sit inside a longer word is not that keyword
  assert.equal(matchesDiscipline('data-engineering', 'Sparkling water sales'), false);
  assert.equal(matchesDiscipline('data-engineering', 'kafkaesque paperwork'), false);
  assert.equal(matchesDiscipline('ai-engineering', 'Said engineer, said the chair'), false, '"ai" inside "said" is not AI');
  assert.equal(matchesDiscipline('technical-program-management', 'We use a tpmx sensor'), false);
  // the last word of a keyword may carry a plural "s", and nothing else may follow it
  assert.ok(matchesDiscipline('technical-program-management', 'Two TPMs share the roadmap'));
  assert.ok(matchesDiscipline('software-engineering', 'Software Engineers wanted'));
  assert.equal(normalize('Data-Lineage!'), ' data lineage ');
});

test('a listing is read from its title and its description together, and belongs to every discipline it names', () => {
  assert.deepEqual(disciplinesFor('Director, Data Platform', 'You will own data quality and data lineage across the estate.'),
    ['data-engineering', 'data-lineage', 'data-quality']);
  assert.deepEqual(disciplinesFor('Chef de cuisine', 'Cooking, and nothing else.'), []);
  // the description alone is enough
  assert.deepEqual(disciplinesFor('Director, Analytics', 'Leading the data governance council.'), ['data-governance']);
});

test('nothing chosen lets every listing through; several chosen are an "or", as the other list filters compose', () => {
  assert.equal(listingMatches([], 'Chef de cuisine', 'Cooking.'), true);
  assert.equal(listingMatches(undefined, 'Chef de cuisine', 'Cooking.'), true);
  assert.equal(listingMatches(['data-quality'], 'Chef de cuisine', 'Cooking.'), false);
  assert.equal(listingMatches(['data-quality', 'software-engineering'], 'Staff Software Engineer', 'Build things.'), true);
  assert.equal(listingMatches(['data-quality', 'software-engineering'], 'Manager, Data Quality', 'Own the checks.'), true);
  assert.equal(listingMatches(['nothing-like-this'], 'Staff Software Engineer', 'Build things.'), false);
});
