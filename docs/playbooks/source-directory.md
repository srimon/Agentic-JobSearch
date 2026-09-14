# Saved source directory

`frontend/app/job-board-links.json` is the versioned manual/search-link catalog rendered
by Sources. It preserves the original PrepPilot search destinations, including LinkedIn,
Indeed, Glassdoor, ZipRecruiter, Dice, Built In, Workday, Monster, SimplyHired, Lever, The Muse, Himalayas, Jooble, USAJOBS and Adzuna.
Workday and Lever links use explicit Google site searches because their postings belong
to individual employer boards. A link does not grant automated access or submission.
Providers can require login or change their search screens.

`config/preppilot_sources.json` separately contains the 55 reviewed public Greenhouse
and Ashby boards. The Hub importer uses provider/board identity and ON CONFLICT DO NOTHING;
it preserves already configured enable/disable settings. Source collection history is
shown in the live database-backed source list. The link catalog does not start ingestion,
create synthetic job rows or bypass matching and owner archive decisions.

Optional JSearch, Serper, Google Custom Search and Brave Search adapters are also
recorded as unconfigured. They are provider integrations, not employer application links.

## Himalayas automated feed

The official no-key API is connected through the existing collector. Source
`himalayas/us-leadership` requests US Director/Executive search results, up to five
20-row pages. The normal classifier still rejects out-of-scope titles and unknown
US eligibility requires review. Epoch publication times are converted to UTC;
expired rows are skipped. Search windows never mark absent jobs closed.

Every saved posting uses its Himalayas guid URL and displayed attribution. Data
is not redistributed to other job boards. The shared proxy allows only the exact
`himalayas.app` host. Manual refreshes and lease retries have a six-hour cooldown;
the daily workflow otherwise retains its normal schedule. Migration 014 creates
the provider disabled; enable only after image and proxy verification. Rollback
requires disabling the source and draining its run before restoring older workers.

Official contract: https://himalayas.app/docs/remote-jobs-api
