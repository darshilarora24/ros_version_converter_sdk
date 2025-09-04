from __future__ import annotations

from pathlib import Path
from typing import List


def basic_checks(pkg_dir: Path) -> List[str]:
    issues = []
    if not (pkg_dir / 'package.xml').exists():
        issues.append('package.xml missing')
    return issues

