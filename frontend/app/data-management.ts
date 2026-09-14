export const dataGroups = [
  {
    "name": "Data Analytics",
    "tools": [
      {
        "id": "clickhouse",
        "name": "ClickHouse",
        "description": "Explore reconciled production public-listing snapshots and the authenticated read-only SQL console. Daily load at 08:30 Pacific.",
        "url": "http://localhost:3105/?view=data-clickhouse",
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
        "description": "Review validation results for Jobsearch.",
        "url": "http://localhost:3105/?view=data-gx",
        "status": "Validation results"
      },
      {
        "id": "soda",
        "name": "SODA",
        "description": "Review scans and measured data-quality findings.",
        "url": "http://localhost:3105/?view=data-soda",
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
        "url": "http://localhost:3105/?view=model",
        "status": "Production schema viewer"
      },
      {
        "id": "catalog",
        "name": "OpenMetadata · Catalog",
        "description": "Explore production PostgreSQL and ClickHouse metadata.",
        "url": "http://localhost:3105/?view=data-catalog",
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
        "url": "http://localhost:3105/?view=data-governance",
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
        "url": "http://localhost:3105/?view=data-lineage",
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
        "url": "http://localhost:3105/?view=data-science",
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
        "url": "http://localhost:3105/?view=data-ingestion",
        "status": "Scheduled Kubernetes Job"
      },
      {
        "id": "dbt",
        "name": "dbt Core",
        "description": "Review dbt validation evidence; ClickHouse transformations use versioned SQL views.",
        "url": "http://localhost:3105/?view=data-dbt",
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
