/**
 * The signed-out card's link to the hub's account screen (app/account-screen.mjs), checked on its own:
 * `npm run test:charts` runs every test in this directory.
 */
import {strict as assert} from 'node:assert';
import test from 'node:test';
import {ACCOUNT_SCREEN, accountScreen, signedOutLanding} from '../app/account-screen.mjs';

test('the screen is the hub\'s, on the bare domain', () => {
  assert.equal(ACCOUNT_SCREEN, 'https://bagala.ai/account/');
});

test('a signed-out visitor on the public site is sent to the screen and comes back to the page asked for, query kept', () => {
  assert.equal(signedOutLanding('https://bagala.ai/jobsearch/?view=saved&job=abc'),
    'https://bagala.ai/account/?next=https%3A%2F%2Fbagala.ai%2Fjobsearch%2F%3Fview%3Dsaved%26job%3Dabc');
  // the old name too; a fragment is not part of the return address, nor is a stale next= of the page's own
  assert.equal(signedOutLanding('https://jobs.bagala.ai/#top'), 'https://bagala.ai/account/?next=https%3A%2F%2Fjobs.bagala.ai%2F');
  assert.equal(signedOutLanding('https://bagala.ai/jobsearch/?view=saved&next=https://evil.example/'),
    'https://bagala.ai/account/?next=https%3A%2F%2Fbagala.ai%2Fjobsearch%2F%3Fview%3Dsaved');
  // a return address another product named is passed on instead of the page
  assert.equal(signedOutLanding('https://bagala.ai/jobsearch/', 'https://bagala.ai/jobprep/start?role=x&company=y'),
    'https://bagala.ai/account/?next=https%3A%2F%2Fbagala.ai%2Fjobprep%2Fstart%3Frole%3Dx%26company%3Dy');
  // a session that was there and is gone says so to the screen
  assert.equal(signedOutLanding('https://bagala.ai/jobsearch/?view=saved', null, 'idle'),
    'https://bagala.ai/account/?signed_out=idle&next=https%3A%2F%2Fbagala.ai%2Fjobsearch%2F%3Fview%3Dsaved');
  assert.equal(signedOutLanding('https://jobs.bagala.ai/', null, 'ended'), 'https://bagala.ai/account/?signed_out=ended&next=https%3A%2F%2Fjobs.bagala.ai%2F');
  assert.equal(signedOutLanding('https://jobs.bagala.ai/', null, 'nonsense'), 'https://bagala.ai/account/?next=https%3A%2F%2Fjobs.bagala.ai%2F');
});

test('the old email landings, the forgot and sign-up flags and a phone\'s code open the screen\'s own pages with the token', () => {
  assert.equal(signedOutLanding('https://bagala.ai/jobsearch/?verify=abc_DEF-123'),
    'https://bagala.ai/account/verify?token=abc_DEF-123&next=https%3A%2F%2Fbagala.ai%2Fjobsearch%2F');
  assert.equal(signedOutLanding('https://jobs.bagala.ai/?reset=tok'), 'https://bagala.ai/account/reset?token=tok&next=https%3A%2F%2Fjobs.bagala.ai%2F');
  assert.equal(signedOutLanding('https://bagala.ai/jobsearch/?forgot=1'), 'https://bagala.ai/account/forgot?next=https%3A%2F%2Fbagala.ai%2Fjobsearch%2F');
  assert.equal(signedOutLanding('https://bagala.ai/jobsearch/?signup=1&view=saved'),
    'https://bagala.ai/account/create?next=https%3A%2F%2Fbagala.ai%2Fjobsearch%2F%3Fview%3Dsaved');
  assert.equal(signedOutLanding('https://bagala.ai/jobsearch/?scan=tok'), 'https://bagala.ai/account/confirm?scan=tok');
  assert.equal(signedOutLanding('https://bagala.ai/jobsearch/?approve=tok'), 'https://bagala.ai/account/approve?code=tok');
  // something that is not a token (spaces, slashes, too long) is not carried: the page is a plain sign-in
  assert.equal(signedOutLanding('https://bagala.ai/jobsearch/?verify=a%20b/c'), 'https://bagala.ai/account/?next=https%3A%2F%2Fbagala.ai%2Fjobsearch%2F');
  assert.equal(signedOutLanding('https://bagala.ai/jobsearch/?reset=' + 'x'.repeat(129)), 'https://bagala.ai/account/?next=https%3A%2F%2Fbagala.ai%2Fjobsearch%2F');
});

test('off the public site nobody is redirected: the card keeps its form', () => {
  for (const href of ['http://localhost:3105/', 'http://localhost:3105/?verify=tok', 'http://127.0.0.1:3105/?next=https://bagala.ai/library/reader',
                      'http://bagala.ai/jobsearch/', 'https://bagala.ai.evil.example/', 'https://evil.example/jobsearch/', 'not a url', '']) {
    assert.equal(signedOutLanding(href), null, href);
  }
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
