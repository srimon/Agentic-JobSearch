# Saved source directory

`frontend/app/job-board-links.json` is the versioned manual/search-link catalog rendered
by Sources. It preserves the original PrepPilot search destinations, including LinkedIn,
Indeed, Glassdoor, ZipRecruiter, Dice, Built In, Workday, Monster, SimplyHired and Lever.
Workday and Lever links use explicit Google site searches because their postings belong
to individual employer boards. A link does not grant automated access or submission.
Providers can require login or change their search screens.

`config/preppilot_sources.json` separately contains the 55 reviewed public Greenhouse
and Ashby boards. The Hub importer uses provider/board identity and ON CONFLICT DO NOTHING;
it preserves already configured enable/disable settings. Source collection history is
shown in the live database-backed source list. The link catalog does not start ingestion,
create synthetic job rows or bypass matching and owner archive decisions.
