/**
 * The prefix rules Job Search is served under (app/base-path.mjs), checked on their own:
 * `npm run test:charts` runs every test in this directory.
 *
 * What matters is that one build answers two addresses. next.config.ts reads mountPath to give
 * Next its basePath; app/paths.ts reads activeBase in the browser to decide which address the
 * visitor is actually on, so bagala.ai/jobsearch/ keeps the prefix on everything it asks for
 * and jobs.bagala.ai asks for exactly what it asks for today.
 */
import {strict as assert} from 'node:assert';
import test from 'node:test';
import {activeBase, mountPath, normalizeBasePath, withBase} from '../app/base-path.mjs';

test('any spelling of the prefix becomes one canonical form', () => {
  for (const raw of ['/jobsearch', 'jobsearch', '/jobsearch/', '  /jobsearch/  ', '/jobsearch//']) {
    assert.equal(normalizeBasePath(raw), '/jobsearch/', raw);
  }
  // A value that names somewhere else is not a prefix: it means the root, never an address.
  for (const raw of ['', '/', undefined, null, 42, 'https://bagala.ai/jobsearch', '//evil.example', '//jobsearch//', '/a/../b', '/.']) {
    assert.equal(normalizeBasePath(raw), '/', String(raw));
  }
  assert.equal(normalizeBasePath('/a/b'), '/a/b/');
});

test('mountPath is what Next and a same-origin URL want: no trailing slash, empty at the root', () => {
  assert.equal(mountPath('/jobsearch'), '/jobsearch');
  assert.equal(mountPath('jobsearch/'), '/jobsearch');
  assert.equal(mountPath(''), '');
  assert.equal(mountPath('/'), '');
});

test('withBase puts an address under the prefix in use and leaves absolute links alone', () => {
  assert.equal(withBase('/jobsearch', '/api/jobs'), '/jobsearch/api/jobs');
  assert.equal(withBase('/jobsearch', '/'), '/jobsearch/');
  assert.equal(withBase('/jobsearch', '/?view=emailed'), '/jobsearch/?view=emailed');
  assert.equal(withBase('/jobsearch', '/__hub/enquiries'), '/jobsearch/__hub/enquiries');
  // The root shape asks for exactly what it asks for today.
  assert.equal(withBase('', '/api/jobs'), '/api/jobs');
  assert.equal(withBase('', '/'), '/');
  // Another product's address, or the public site, is never rewritten.
  for (const absolute of ['https://prep.bagala.ai/', 'https://bagala.ai/jobprep/', '//www.bagala.ai/help']) {
    assert.equal(withBase('/jobsearch', absolute), absolute);
  }
});

test('activeBase reads the address the visitor is on, not the one the build was made with', () => {
  // https://bagala.ai/jobsearch/... — the short path on the shared host.
  for (const pathname of ['/jobsearch', '/jobsearch/', '/jobsearch/anything']) {
    assert.equal(activeBase('/jobsearch', pathname), '/jobsearch', pathname);
  }
  // https://jobs.bagala.ai/ and http://localhost:3105/ — the same build, served at the root.
  for (const pathname of ['/', '', '/anything']) {
    assert.equal(activeBase('/jobsearch', pathname), '', pathname);
  }
  // A name that merely starts with the prefix is not under it.
  assert.equal(activeBase('/jobsearch', '/jobsearchers'), '');
  // A build with no prefix is always at the root.
  assert.equal(activeBase('', '/jobsearch/x'), '');
});
