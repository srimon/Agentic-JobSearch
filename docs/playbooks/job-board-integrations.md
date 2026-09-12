# Job-board integration status

Dice: connected through the officially documented public endpoint https://mcp.dice.com/mcp. No credentials required. The adapter uses only the read-only search_jobs tool and a fixed hostname with public-IP checks, verified TLS, no redirects, bounded responses and timeouts. Eleven fixed US leadership queries fetch at most two pages of 100 results each, sorted by posting date. Results are a bounded search snapshot, not all Dice listings. Summary text is labeled as a summary in stored evidence; postedDate is used and modifiedDate is never substituted. Employer identity and source/company links are preserved. Duplicate Dice job IDs across queries are removed; cross-provider deduplication is not implemented. Source failures do not mark older data closed. Rate-limited runs fail visibly and are retried on the next scheduled or manual refresh.

Indeed: search link available; ingestion unconnected. Current official docs describe OAuth/partner credentials for jobSearch. An ordinary job-seeker login is not an API credential. Reference: https://docs.indeed.com/getstarted/integrate-and-call-apis

LinkedIn: search link available; ingestion unconnected. Published Job Posting APIs manage employer postings and do not establish access to a general searchable job feed. Reference: https://learn.microsoft.com/en-us/linkedin/talent/job-postings/api/overview

Monster: search link available; ingestion unconnected. A supported public search API was not verified. Requires a supported feed/integration before automated collection is enabled.

Do not paste account passwords, verification codes or session cookies into chat or source configuration. Employer ATS sources remain independent of these job-board integrations.

Dice reference: https://www.dice.com/career-advice/how-to-connect-the-dice-mcp-server-to-your-ai-assistant


Additional no-key feeds: Jobicy (latest 200 US remote records) and Remotive (public remote feed delayed 24 hours). Both retain source attribution and original listing URLs. Scheduled polling is six-hourly; manual requests enforce a one-hour Jobicy and six-hour Remotive cooldown, including failed network runs. Remotive is used for this private personal workspace, not public signup collection or redistribution to third-party job boards. Missing timezone information is not guessed: such dates remain unknown and are excluded from date-window searches.

Google: manual discovery link only. Its Custom Search JSON API is closed to new customers; existing customers must transition by January 1, 2027. No Google Search/Jobs crawling or paid search API is configured. Google Indexing API submits updates about publisher-owned job pages; it is not a searchable jobs feed.

References:
- https://developers.google.com/custom-search/v1/overview
- https://jobicy.com/jobs-rss-feed
- https://github.com/remotive-io/remote-jobs-api

Active coverage now includes ten employer boards across Ashby, Greenhouse and Lever, plus Dice, Jobicy and Remotive. This is bounded coverage, not all jobs on the internet. Cross-source duplicate detection remains future work; within-source identifiers are deduplicated.

## Scheduled source verification — 2026-09-11
OpenAI public Ashby board `openai` was verified against the official OpenAI careers page and Ashby public job-posting API documentation. The network-enabled collector probe returned 789 postings; the durable collection retained one review candidate and no matching US leadership roles. Enabled through the existing source registry. Engine was already registered and was not duplicated. Public probes belong in the worker network, not the API container. References: https://openai.com/careers/search/ and https://developers.ashbyhq.com/docs/public-job-posting-api .
