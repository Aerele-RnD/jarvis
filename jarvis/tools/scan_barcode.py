"""Resolve a barcode (or serial / batch number) to its Item context.

Wraps ``erpnext.stock.utils.scan_barcode``. Used in mobile / kiosk
workflows where the agent receives a raw scanned value and needs to
know what item it is, what serial / batch is implied, and what
warehouse the scan happened in.

Read-only - no DB writes, just a lookup. Permission gating is the
underlying helper's responsibility (it consults Item / Serial No /
Batch read perms).
"""
from __future__ import annotations

from jarvis.exceptions import InvalidArgumentError


def scan_barcode(search_value: str) -> dict:
    """Look ``search_value`` up across Barcode, Serial No, and Batch
    No tables. Returns whatever ERPNext's resolver finds, typically
    ``{item_code, barcode, serial_no, batch_no, ...}`` - shape varies
    by what the scanner matched."""
    if not search_value:
        raise InvalidArgumentError("search_value is required")

    from erpnext.stock.utils import scan_barcode as _scan

    result = _scan(search_value=search_value)
    # The underlying helper returns a typed dataclass (BarcodeScanResult)
    # or a dict depending on the ERPNext release; normalise to a JSON-
    # friendly dict either way.
    if hasattr(result, "__dict__"):
        return {k: v for k, v in vars(result).items() if not k.startswith("_")}
    if isinstance(result, dict):
        return result
    return {"raw": result}
