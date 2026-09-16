/**
 * The build's prefix, and the one the address in the browser is actually under.
 *
 * base-path.mjs holds the rules; this binds them to the build (NEXT_PUBLIC_JOBSEARCH_BASE_PATH,
 * the same value next.config.ts gives Next as `basePath`) and to the live address. Every
 * same-origin URL the application builds — API calls, the sign-in landing, the enquiry form —
 * goes through `withBase`, so bagala.ai/jobsearch/ keeps the prefix and jobs.bagala.ai does not.
 */
import {activeBase, mountPath, withBase as join} from './base-path.mjs';

/** The prefix this build was made under: "" at the root, "/jobsearch" on the short path. */
export const BUILD_BASE: string = mountPath(process.env.NEXT_PUBLIC_JOBSEARCH_BASE_PATH ?? '/jobsearch');

/**
 * The prefix of the address being shown. One build serves both addresses, so this is read from
 * the browser rather than baked in; on the server (there is no pre-rendered page that needs it)
 * it is the build's own prefix.
 */
export function base(): string {
  return typeof window === 'undefined' ? BUILD_BASE : activeBase(BUILD_BASE, window.location.pathname);
}

/** A same-origin address on the prefix in use; an absolute URL is returned unchanged. */
export function withBase(path: string): string {
  return join(base(), path);
}

/**
 * True when an address belongs to this product rather than another one.
 *
 * At the root shape the whole origin is Job Search, so same-origin is enough; on the shared
 * host bagala.ai carries several products, and only what is under this prefix is ours. A
 * ?next= that names bagala.ai/jobprep/... is therefore somewhere else to be sent back to, not
 * the page the visitor is already on.
 */
export function isOwnAddress(raw: string): boolean {
  let url: URL;
  try {
    url = new URL(raw, window.location.href);
  } catch {
    return false;
  }
  if (url.origin !== window.location.origin) {
    return false;
  }
  const prefix = base();
  return !prefix || url.pathname === prefix || url.pathname.startsWith(prefix + '/');
}

/** How an address reads to a person: "bagala.ai/jobprep", "library.bagala.ai". */
export function addressLabel(raw: string): string {
  let url: URL;
  try {
    url = new URL(raw, window.location.href);
  } catch {
    return '';
  }
  const first = url.pathname.split('/').filter(Boolean)[0];
  return url.host + (first ? '/' + first : '');
}
