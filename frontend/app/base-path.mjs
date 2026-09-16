/**
 * The path prefix Job Search is served under.
 *
 * While the products move from subdomains to short paths on one host, Job Search answers on
 * https://bagala.ai/jobsearch/ (the short path) and on https://jobs.bagala.ai/ and
 * http://localhost:3105/ (the root shape), from one build and one deployment.
 *
 * Next bakes `basePath` into the build — the asset URLs under /_next, the icon link and the
 * sources of the /api rewrite all carry it — so the build is made once, under the prefix, and
 * the gateway gives the prefix to a request that arrives at the root shape
 * (platform/gateway/nginx.conf). Everything the browser is shown or asked to fetch is built
 * from the address it is actually on instead: `activeBase` reads that from the pathname, so a
 * visitor on jobs.bagala.ai calls /api/... and one on bagala.ai/jobsearch/ calls
 * /jobsearch/api/..., and each address returns to itself.
 *
 * Pure module: no React, no import.meta, no process.env, so node --test loads it directly
 * (frontend/tests/base-path.test.mjs) and next.config.ts can read it while it builds.
 */

/** A prefix is one or more plain path segments; anything else means "no prefix". */
const SEGMENT = /^[A-Za-z0-9._~-]+$/;

/** Already absolute (scheme-relative or with a scheme): left exactly as it is. */
const ABSOLUTE = /^(?:[A-Za-z][A-Za-z0-9+.-]*:|\/\/)/;

/**
 * Any accepted spelling as one canonical form: "/" or "/jobsearch/", always with a leading and
 * a trailing slash. Empty, absent, absolute or traversing values all mean the root.
 *
 * @param {unknown} raw
 * @returns {string}
 */
export function normalizeBasePath(raw) {
  const text = typeof raw === 'string' ? raw.trim() : '';

  if (!text || ABSOLUTE.test(text)) {
    return '/';
  }

  const segments = text.split('/').filter(Boolean);

  if (!segments.length || !segments.every((segment) => SEGMENT.test(segment) && segment !== '.' && segment !== '..')) {
    return '/';
  }

  return `/${segments.join('/')}/`;
}

/**
 * The prefix without its trailing slash: "" for the root and "/jobsearch" otherwise. This is
 * exactly what Next wants as `basePath` and what a same-origin URL is built from.
 *
 * @param {unknown} base
 * @returns {string}
 */
export function mountPath(base) {
  const prefix = normalizeBasePath(base);

  return prefix === '/' ? '' : prefix.slice(0, -1);
}

/**
 * A same-origin address under a prefix: withBase('/jobsearch', '/api/jobs') is
 * '/jobsearch/api/jobs', and the same call with '' is '/api/jobs'. Query and hash ride along
 * untouched; an absolute URL is returned unchanged, so a link that already names another
 * product is never rewritten.
 *
 * @param {unknown} base
 * @param {unknown} path
 * @returns {string}
 */
export function withBase(base, path) {
  const prefix = normalizeBasePath(base);
  const text = typeof path === 'string' ? path : '';

  if (ABSOLUTE.test(text)) {
    return text;
  }

  return prefix + text.replace(/^\/+/, '');
}

/**
 * The prefix an address is actually being served under: the build's prefix when the pathname
 * is under it, "" otherwise. A name that merely starts with the prefix ("/jobsearchers") is
 * not under it.
 *
 * @param {unknown} base the prefix this build was made with
 * @param {unknown} pathname window.location.pathname
 * @returns {string} "" or the prefix without its trailing slash
 */
export function activeBase(base, pathname) {
  const prefix = mountPath(base);
  const text = typeof pathname === 'string' ? pathname : '';

  if (!prefix) {
    return '';
  }

  return text === prefix || text.startsWith(prefix + '/') ? prefix : '';
}
