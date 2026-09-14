# Refresh completeness and listing visibility

Successful collection does not always establish that the source's entire job
inventory was observed. Dice search pages and Jobicy/Remotive public feeds are
windows. A previously seen job absent from one of those windows must not be
marked `not_observed` solely for that reason.

`collect_snapshot` carries explicit `complete_board` metadata. Only successful
Ashby, Greenhouse and fully paginated Lever board reads currently set it.
Unknown future providers default to incomplete. Failed pagination raises an
error, so the run cannot reconcile availability or report completion.
The worker records this distinction in its completion audit event.

This changes future refreshes. It does not reopen archived jobs, reverse owner
decisions, or claim that older records hidden by the previous implementation
are still open. Those records require new source evidence.

Application status for a displayed page is loaded in one owner-filtered query
and decrypted with the existing owner/job binding. The limit remains 25 jobs;
only status and next action enter the list response. Recommendation-model
training and full-result sorting remain separate performance work.

Run `python -m unittest evaluation.test_collection_completeness
evaluation.test_application_summaries` for the isolated regression checks.
The PostgreSQL integration suite must use `jobsearch_auth_test` in a disposable
database, never application credentials or production state.
