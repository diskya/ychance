from __future__ import annotations

from pathlib import Path


def test_empirical_test_does_not_import_rawstore() -> None:
    root = Path(__file__).resolve().parents[2] / "empirical_test"
    offenders: list[tuple[Path, str]] = []
    for path in root.rglob("*.py"):
        for line in path.read_text().splitlines():
            stripped = line.strip()
            if stripped.startswith("from rawstore") or stripped.startswith("import rawstore"):
                offenders.append((path, stripped))
    assert offenders == []
