"""Redact query text from local retrieval telemetry."""

VERSION = 9
NAME = "redact_retrieval_metric_queries"

SQL = ""

# The runner includes this explicit marker in the immutable migration checksum.
DATA_MIGRATION_VERSION = "redact-query-text-v1"


def migrate_data(connection) -> None:
    """Remove historical MCP query text while retaining aggregate metric rows."""
    connection.execute(
        "UPDATE retrieval_metrics SET query = ? WHERE query <> ?",
        ("[redacted]", "[redacted]"),
    )
