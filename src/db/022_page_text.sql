-- The shared text store (the owner's 18 September batch, section 5): the words an administrator has changed on a
-- screen, for every Bagala surface. Job Search owns accounts, so it owns this table and the two routes over it
-- (src/api/page_text.py): GET /api/hub/page-text is public and returns {key: value}; PUT is administrator-only,
-- same-origin like every other write, and records who wrote each value and when.
--
-- key is "<page>.<slug>" - the data-text attribute a surface puts on a static heading, lede, paragraph, option
-- label or button caption. Live data, names and numbers are never marked and never stored here. value is plain
-- text of at most 2000 characters; the route refuses control characters and anything HTML-shaped, and every
-- surface writes it with textContent, never innerHTML. An empty value is not stored: the route deletes the row,
-- which is how "Reset this page to the original" puts a screen back to the words in its source.
--
-- updated_by is the account id of the administrator who wrote the value and updated_at_utc the second they did,
-- so the write is attributable here as well as in jobsearch.audit_events. No personal name is stored, and the
-- public GET returns only the keys and their values. Additive: nothing reads this table until a surface asks.
CREATE TABLE IF NOT EXISTS jobsearch.page_text (
 key text PRIMARY KEY CHECK(key ~ '^[a-z0-9]+(\.[a-z0-9-]+)+$' AND char_length(key) <= 120),
 value text NOT NULL CHECK(char_length(value) BETWEEN 1 AND 2000),
 updated_by text,
 updated_at_utc bigint
);
GRANT SELECT,INSERT,UPDATE,DELETE ON jobsearch.page_text TO jobsearch_app;
INSERT INTO jobsearch.schema_versions(version) VALUES(22) ON CONFLICT DO NOTHING;
