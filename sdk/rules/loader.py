from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List


def _strip_comment(line: str) -> str:
    # remove inline comments starting with # (not in quotes for simplicity)
    if '#' in line:
        return line.split('#', 1)[0].rstrip()
    return line.rstrip()


def load_simple_yaml(path: Path) -> Dict[str, Any]:
    """
    Very small YAML-like parser for our simple rules files.
    Supports:
      - top-level and one-level nested mappings: key:\n  subkey: value
      - string scalar values
      - lists with '- item' lines
    Not a general YAML parser; only for our rules files.
    """
    data: Dict[str, Any] = {}
    current_map: Dict[str, Any] | None = None
    current_list_key: str | None = None
    with path.open('r', encoding='utf-8') as f:
        for raw in f:
            line = _strip_comment(raw)
            if not line.strip():
                continue
            # list item
            if line.lstrip().startswith('- '):
                if current_map is not None and current_list_key is not None:
                    item = line.strip()[2:].strip()
                    current_map.setdefault(current_list_key, []).append(item)
                else:
                    # top-level list not supported; skip
                    continue
                continue
            # mapping
            if ':' in line:
                indent = len(line) - len(line.lstrip(' '))
                key, val = line.split(':', 1)
                key = key.strip()
                val = val.strip()
                if indent == 0:
                    current_list_key = None
                    if not val:
                        # start nested mapping
                        current_map = {}
                        data[key] = current_map
                    else:
                        data[key] = val
                        current_map = None
                else:
                    if current_map is None:
                        # malformed; skip
                        continue
                    if not val:
                        # nested list or map starting; assume list will follow
                        current_map[key] = []
                        current_list_key = key
                    else:
                        current_map[key] = val
                        current_list_key = None
    return data


def load_api_rules(rules_dir: Path) -> Dict[str, Any]:
    return load_simple_yaml(rules_dir / 'api_python.yaml')


def load_qos_rules(rules_dir: Path) -> Dict[str, Any]:
    return load_simple_yaml(rules_dir / 'qos.yaml')

