"""One tuner-status model for Python, mirroring the Java `Status` fields.

`as_dict()` keeps the old CLI/JSON shape byte-compatible; the mapping helpers
let existing callers keep using `status["raw_strength"]` / `status.get(...)`.
"""

from dataclasses import dataclass
from typing import Any, Dict, Iterator, Optional, Tuple


@dataclass
class Status:
    locked: bool = False
    raw_strength: int = -1
    strength_percent: int = -1
    raw_quality: int = -1
    quality_percent: int = -1
    dbm: int = -1000
    raw_snr: int = -1
    snr_db: Optional[int] = None
    ber_errors: int = -1
    ber_window: int = -1
    ber: Optional[float] = None

    def as_dict(self) -> Dict[str, Any]:
        return {
            "locked": self.locked,
            "raw_strength": self.raw_strength,
            "strength_percent": self.strength_percent,
            "raw_quality": self.raw_quality,
            "quality_percent": self.quality_percent,
            "dbm": self.dbm,
            "raw_snr": self.raw_snr,
            "snr_db": self.snr_db,
            "ber_errors": self.ber_errors,
            "ber_window": self.ber_window,
            "ber": self.ber,
        }

    # Mapping compatibility, so the CLI and older callers keep working.
    def __getitem__(self, key: str) -> Any:
        return self.as_dict()[key]

    def get(self, key: str, default: Any = None) -> Any:
        return self.as_dict().get(key, default)

    def __iter__(self) -> Iterator[str]:
        return iter(self.as_dict())

    def keys(self):
        return self.as_dict().keys()

    def values(self):
        return self.as_dict().values()

    def items(self) -> Iterator[Tuple[str, Any]]:
        return iter(self.as_dict().items())

    def __repr__(self) -> str:
        return repr(self.as_dict())
