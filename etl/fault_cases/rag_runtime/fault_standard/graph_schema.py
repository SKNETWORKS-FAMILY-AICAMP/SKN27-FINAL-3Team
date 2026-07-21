"""Stable labels and Cypher fragments for the operational fault graph."""

from __future__ import annotations

import re


OPERATIONAL_LABEL = "FaultStandardOperational"
LEGACY_EXPERIMENT_LABELS = frozenset({"Complete30V7", "Complete30V9", "V9Import"})
SAFE_IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def node_pattern(alias: str, role_label: str) -> str:
    if not SAFE_IDENTIFIER.fullmatch(alias) or not SAFE_IDENTIFIER.fullmatch(role_label):
        raise ValueError("Cypher alias and role label must be safe identifiers")
    return f"({alias}:{OPERATIONAL_LABEL}:{role_label})"
