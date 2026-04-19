from __future__ import annotations

from pathlib import Path
from typing import List
from xml.etree import ElementTree as ET


def _todo_count_in_dir(pkg_dir: Path) -> int:
    count = 0
    for py_file in pkg_dir.rglob('*.py'):
        try:
            count += py_file.read_text(encoding='utf-8').count('TODO')
        except Exception:
            pass
    return count


def _detect_package_name(pkg_dir: Path) -> str | None:
    pkg_xml = pkg_dir / 'package.xml'
    if not pkg_xml.exists():
        return None
    try:
        root = ET.parse(str(pkg_xml)).getroot()
        el = root.find('name')
        return el.text.strip() if el is not None and el.text else None
    except Exception:
        return None


def basic_checks(pkg_dir: Path) -> List[str]:
    issues: List[str] = []

    if not (pkg_dir / 'package.xml').exists():
        issues.append('package.xml missing')
    else:
        try:
            root = ET.parse(str(pkg_dir / 'package.xml')).getroot()
            exec_deps = [d.text.strip() for d in root.findall('exec_depend') if d.text]
            if 'rclpy' not in exec_deps:
                issues.append('rclpy missing from exec_depend in package.xml')
        except Exception as exc:
            issues.append(f'package.xml parse error: {exc}')

    if not (pkg_dir / 'setup.cfg').exists():
        issues.append('setup.cfg missing')

    if not (pkg_dir / 'pyproject.toml').exists():
        issues.append('pyproject.toml missing')

    pkg_name = _detect_package_name(pkg_dir)
    if pkg_name:
        module_dir = pkg_dir / pkg_name
        if not module_dir.is_dir():
            issues.append(f'Python module directory {pkg_name}/ missing')
        elif not (module_dir / '__init__.py').exists():
            issues.append(f'{pkg_name}/__init__.py missing')

    todo_count = _todo_count_in_dir(pkg_dir)
    if todo_count > 0:
        issues.append(f'{todo_count} TODO item(s) require manual attention')

    return issues
