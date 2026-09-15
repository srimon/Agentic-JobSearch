export const dataGroups = [
  {
    "name": "Data Analytics",
    "tools": [
      {
        "id": "clickhouse",
        "name": "ClickHouse",
        "description": "Explore reconciled production public-listing snapshots and the authenticated read-only SQL console. Daily load at 08:30 Pacific.",
        "url": "/?view=data-clickhouse",
        "status": "Production analytics"
      }
    ]
  },
  {
    "name": "Data Quality",
    "tools": [
      {
        "id": "gx",
        "name": "Great Expectations",
        "description": "Review validation results for Job Search.",
        "url": "/?view=data-gx",
        "status": "Validation results"
      },
      {
        "id": "soda",
        "name": "SODA",
        "description": "Review scans and measured data-quality findings.",
        "url": "/?view=data-soda",
        "status": "Validation results"
      }
    ]
  },
  {
    "name": "Data Modelling",
    "tools": [
      {
        "id": "model",
        "name": "PostgreSQL · SchemaSpy",
        "description": "Explore production tables and declared relationships using an empty schema copy.",
        "url": "/?view=model",
        "status": "Production schema viewer"
      },
      {
        "id": "catalog",
        "name": "OpenMetadata · Catalog",
        "description": "Explore production PostgreSQL and ClickHouse metadata.",
        "url": "/?view=data-catalog",
        "status": "Production catalog"
      }
    ]
  },
  {
    "name": "Data Governance",
    "tools": [
      {
        "id": "governance",
        "name": "OpenMetadata",
        "description": "Review business definitions, suggested classifications and stewardship assignments.",
        "url": "/?view=data-governance",
        "status": "Catalog and governance"
      }
    ]
  },
  {
    "name": "Data Lineage",
    "tools": [
      {
        "id": "lineage",
        "name": "OpenMetadata · Lineage",
        "description": "Follow declared dependencies from PostgreSQL to current ClickHouse listings and ML features.",
        "url": "/?view=data-lineage",
        "status": "Verified pipeline lineage"
      }
    ]
  },
  {
    "name": "Data Science",
    "tools": [
      {
        "id": "science",
        "name": "ML feature dataset",
        "description": "Inspect reproducible public-listing features. No notebook workspace or model training is configured.",
        "url": "/?view=data-science",
        "status": "Feature dataset available"
      }
    ]
  },
  {
    "name": "Data Engineering",
    "tools": [
      {
        "id": "ingestion",
        "name": "ClickHouse ingestion",
        "description": "Reconciled daily snapshot from production PostgreSQL at 08:30 Pacific after source collection.",
        "url": "/?view=data-ingestion",
        "status": "Scheduled Kubernetes Job"
      },
      {
        "id": "dbt",
        "name": "dbt Core",
        "description": "Review dbt validation evidence; ClickHouse transformations use versioned SQL views.",
        "url": "/?view=data-dbt",
        "status": "Validation results"
      },
      {
        "id": "dag",
        "name": "DAG scheduler",
        "description": "Current collection and analytics use Kubernetes schedules. A visual DAG editor is not configured.",
        "url": "",
        "status": "Not configured"
      }
    ]
  }
];
