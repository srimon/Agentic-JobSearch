# Public source failures and URL normalization

The Greenhouse `block` feed emits HTTP links to Block's careers site. The
collector upgrades only `http://block.xyz/careers/jobs/<job-id>` with no query
or a matching `gh_jid` query to HTTPS. The feed's job ID must match the path.
User information, ports, other hosts, fragments and additional query arguments
do not qualify. Each normalized row records `https_upgrade` in its evidence.
All rows still pass the existing HTTPS-only validation. An unapproved URL
fails the board instead of silently turning a partial refresh into a complete
board snapshot.

`tests/test_block_urls.py` checks the accepted conversion, unsafe destinations,
unchanged HTTPS links and complete-board failure behavior. It runs in CI with
the collector integration checks.

A source that returns HTTP 404 needs an operator review of its actual employer
and board identity. Pause polling when no replacement is verified; retain its
failure, existing jobs and run history. A similarly named company's board is
not sufficient evidence to retarget it. Re-enable only after verifying a valid
public endpoint for the same source.

After a transport or parser repair, enqueue one bounded collection through the
existing supervisor and observe its durable result. Initialization alone does
not prove collection works. Do not replay the daily application/report workflow
as a source-health test. Current production results and image provenance are
maintained in the parent Hub's source-repair runbook.
