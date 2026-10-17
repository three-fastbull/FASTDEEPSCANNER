"""FastDeep stock scanner MVP."""

from .net import prefer_ipv4

prefer_ipv4()

from .models import ScanCriteria, ScanResult  # noqa: E402
from .scanner import scan_market

__all__ = ["ScanCriteria", "ScanResult", "scan_market"]
