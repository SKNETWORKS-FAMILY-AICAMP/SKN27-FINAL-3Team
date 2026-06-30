"""Check importability and syntax correctness of database loaders and exporters."""

from __future__ import annotations

import sys


def check_imports():
    print("Verifying imports for database modules...")
    try:
        import psycopg2
        print("-> psycopg2 imported successfully.")
    except ImportError as exc:
        print(f"-> psycopg2 import failed (expected if not installed in this environment): {exc}")

    try:
        from neo4j import GraphDatabase
        print("-> neo4j driver imported successfully.")
    except ImportError as exc:
        print(f"-> neo4j driver import failed: {exc}")

    try:
        import numpy as np
        print("-> numpy imported successfully.")
    except ImportError as exc:
        print(f"-> numpy import failed: {exc}")

    try:
        import yaml
        print("-> yaml imported successfully.")
    except ImportError as exc:
        print(f"-> yaml import failed: {exc}")

    try:
        from etl.legal.load_sql import load_to_postgres
        print("-> etl.legal.load_sql.load_to_postgres imported successfully.")
    except Exception as exc:
        print(f"ERROR: Failed to import load_to_postgres: {exc}")
        return False

    try:
        from etl.legal.export_neo4j import import_similarity_relations, import_legal_artifacts
        print("-> etl.legal.export_neo4j functions imported successfully.")
    except Exception as exc:
        print(f"ERROR: Failed to import export_neo4j functions: {exc}")
        return False

    return True


if __name__ == "__main__":
    success = check_imports()
    if success:
        print("\nAll database modules are syntactically valid and importable!")
        sys.exit(0)
    else:
        print("\nDatabase module check FAILED due to syntax or logical error.", file=sys.stderr)
        sys.exit(1)
