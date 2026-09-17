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
