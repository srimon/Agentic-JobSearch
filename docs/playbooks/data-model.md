# PostgreSQL data model

Staging operators can select Data model or open `http://localhost:3185/?view=model` to browse the actual SchemaSpy report. It shows the schema capture time, table count and declared foreign-key count. Reload reads the latest saved snapshot; generation is performed using the Hub staging_data_model operator CLI, after schema changes.

Every metadata/report/asset request requires operator access and is unavailable against the production database. No sample records, comments, defaults, routines or inferred relationships are included. The production migration remains paused.
