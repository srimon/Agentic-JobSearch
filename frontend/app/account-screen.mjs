/**
 * The hub's product-neutral account screen (https://bagala.ai/account/, served by the public edge from the
 * welcome tree; docs/plans/account-screen.md in the hub repository).
 *
 * On the public site every product's "Sign in" goes there, and so does this one: the signed-out card offers a
 * link to the screen rather than its own form, and the screen sends the person back here afterwards. The
 * screen exists only behind the public edge, so on the loopback name (and anywhere else) the card keeps its
 * own form. Plain JavaScript so `npm run test:charts` (node --test tests/) can check the rule on its own.
 */
export const ACCOUNT_SCREEN = 'https://bagala.ai/account/';
/** The names the screen returns to: the shared host and the four product names (the screen's own list). */
const HOSTS = ['bagala.ai', 'hub.bagala.ai', 'library.bagala.ai', 'prep.bagala.ai', 'jobs.bagala.ai'];
/** This page's own handled parameters, and the screen's page for the ones that carry a token: the old email
 *  landings (the mails point at the screen since 302d928, but an old mail may still be opened) and a phone's code. */
const LANDINGS = {verify: 'verify?token=', reset: 'reset?token=', scan: 'confirm?scan=', approve: 'approve?code='};
const HANDLED = ['next', 'verify', 'reset', 'forgot', 'signup', 'scan', 'approve'];
const TOKEN = /^[A-Za-z0-9_-]{1,128}$/;

/**
 * Where a signed-out visitor to `href` goes on the public site, at once (page.tsx replaces the address as soon as
 * the session check says signed out, so this product's page behaves like the others behind the hub's gateways):
 * the screen's own page for an old email landing (?verify=, ?reset=, ?forgot=) or a phone's code (?scan=, ?approve=),
 * the create page for ?signup, else the sign-in page; each with the return address, which is `next` when another
 * product named one, else this page without its handled parameters and fragment, query kept. `reason` ('idle' or
 * 'ended') tells the screen that a session was there and is gone. null off the public site, where the card keeps
 * its form, and a signed-in visitor is never sent (the caller checks the session first).
 */
export function signedOutLanding(href, next, reason) {
  let page;
  try {
    page = new URL(href);
  } catch {
    return null;
  }
  if (page.protocol !== 'https:' || !HOSTS.includes(page.hostname)) {
    return null;
  }
  const found = {};
  for (const key of Object.keys(LANDINGS)) {
    const value = page.searchParams.get(key);
    found[key] = value && TOKEN.test(value) ? value : null;
  }
  const forgot = page.searchParams.has('forgot'), signup = page.searchParams.has('signup');
  page.hash = '';
  for (const key of HANDLED) page.searchParams.delete(key);
  const back = encodeURIComponent(next || page.href);
  if (found.scan) return ACCOUNT_SCREEN + LANDINGS.scan + found.scan;
  if (found.approve) return ACCOUNT_SCREEN + LANDINGS.approve + found.approve;
  if (found.verify) return ACCOUNT_SCREEN + LANDINGS.verify + found.verify + '&next=' + back;
  if (found.reset) return ACCOUNT_SCREEN + LANDINGS.reset + found.reset + '&next=' + back;
  if (forgot) return ACCOUNT_SCREEN + 'forgot?next=' + back;
  if (signup) return ACCOUNT_SCREEN + 'create?next=' + back;
  const why = reason === 'idle' || reason === 'ended' ? 'signed_out=' + reason + '&' : '';
  return ACCOUNT_SCREEN + '?' + why + 'next=' + back;
}

/**
 * The screen's addresses for a page at `href`, told to come back to `next` (a return address another product
 * named) or, without one, to the page itself without its fragment and without a stale next= of its own.
 * null when the page is not on the public site over https: loopback keeps the form.
 */
export function accountScreen(href, next) {
  let page;
  try {
    page = new URL(href);
  } catch {
    return null;
  }
  if (page.protocol !== 'https:' || !HOSTS.includes(page.hostname)) {
    return null;
  }
  page.hash = '';
  page.searchParams.delete('next');
  const back = next || page.href;
  return {
    signIn: ACCOUNT_SCREEN + '?next=' + encodeURIComponent(back),
    create: ACCOUNT_SCREEN + 'create?next=' + encodeURIComponent(back),
  };
}
