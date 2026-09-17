/**
 * The signed-out card's link to the hub's account screen (app/account-screen.mjs), checked on its own:
 * `npm run test:charts` runs every test in this directory.
 */
import {strict as assert} from 'node:assert';
import test from 'node:test';
import {ACCOUNT_SCREEN, accountScreen} from '../app/account-screen.mjs';

test('the screen is the hub\'s, on the bare domain', () => {
  assert.equal(ACCOUNT_SCREEN, 'https://bagala.ai/account/');
});

test('on the public site the card links to the screen and comes back to the page itself', () => {
  assert.deepEqual(accountScreen('https://bagala.ai/jobsearch/?view=saved'), {
    signIn: 'https://bagala.ai/account/?next=https%3A%2F%2Fbagala.ai%2Fjobsearch%2F%3Fview%3Dsaved',
    create: 'https://bagala.ai/account/create?next=https%3A%2F%2Fbagala.ai%2Fjobsearch%2F%3Fview%3Dsaved',
  });
  assert.equal(accountScreen('https://jobs.bagala.ai/').signIn, 'https://bagala.ai/account/?next=https%3A%2F%2Fjobs.bagala.ai%2F');
  // A fragment is not part of the return address, and a stale next= of this page's own is not nested inside it.
  assert.equal(accountScreen('https://bagala.ai/jobsearch/?view=saved&next=https://evil.example/#top').signIn,
    'https://bagala.ai/account/?next=https%3A%2F%2Fbagala.ai%2Fjobsearch%2F%3Fview%3Dsaved');
});

test('a return address another product named is passed on instead of the page', () => {
  assert.equal(accountScreen('https://bagala.ai/jobsearch/', 'https://bagala.ai/jobprep/start?role=x&company=y').signIn,
    'https://bagala.ai/account/?next=https%3A%2F%2Fbagala.ai%2Fjobprep%2Fstart%3Frole%3Dx%26company%3Dy');
});

test('off the public site the card keeps its own form', () => {
  for (const href of ['http://localhost:3105/', 'http://127.0.0.1:3105/?next=https://bagala.ai/library/reader', 'http://bagala.ai/jobsearch/',
                      'https://bagala.ai.evil.example/', 'https://evil.example/jobsearch/', 'not a url', '']) {
    assert.equal(accountScreen(href), null, href);
  }
});
