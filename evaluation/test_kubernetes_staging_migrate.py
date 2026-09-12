import pytest

from scripts import kubernetes_staging_migrate as migration


VALID = "postgresql://jobsearch_owner:secret@postgres:5432/jobsearch_staging"


def test_accepts_only_guarded_staging_target():
    migration.validate_target(VALID, "1", "a" * 24)
    rejected = [
        VALID.replace("postgres", "127.0.0.1"),
        VALID.replace("jobsearch_staging", "jobsearch"),
        VALID.replace("jobsearch_owner", "jobsearch_app"),
        VALID.replace(":5432", ":5544"),
    ]
    for dsn in rejected:
        with pytest.raises(migration.StagingMigrationError):
            migration.validate_target(dsn, "1", "a" * 24)


def test_requires_explicit_flag_strong_password_and_all_migrations():
    with pytest.raises(migration.StagingMigrationError):
        migration.validate_target(VALID, "0", "a" * 24)
    with pytest.raises(migration.StagingMigrationError):
        migration.validate_target(VALID, "1", "short")
    assert [path.name[:3] for path in migration.MIGRATIONS] == [f"{version:03d}" for version in migration.EXPECTED_VERSIONS]
