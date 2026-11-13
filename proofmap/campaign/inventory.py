"""Pure source inventory counts shared by campaign planning and presentation."""

from __future__ import annotations

from typing import Any


def unresolved_region_count(document_ir: dict[str, Any]) -> int:
    """Count the existing unresolved assertion/proof roles, not unsupported targets."""
    return sum(
        element["kind"] in {"ASSERTION", "PROOF"} and element.get("role") == "UNRESOLVED"
        for element in document_ir["elements"]
    )
