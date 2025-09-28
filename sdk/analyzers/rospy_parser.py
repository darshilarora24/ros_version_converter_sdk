from __future__ import annotations

import ast
from pathlib import Path
from typing import List, Optional

from sdk.ir.model import NodeIR, TopicIR


def _is_rospy_import(node: ast.AST) -> bool:
    if isinstance(node, ast.Import):
        return any(n.name == 'rospy' for n in node.names)
    if isinstance(node, ast.ImportFrom):
        return node.module == 'rospy'
    return False


def _expr_to_str(node: ast.AST) -> Optional[str]:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        parts: List[str] = []
        current: ast.AST = node
        while isinstance(current, ast.Attribute):
            parts.append(current.attr)
            current = current.value
        if isinstance(current, ast.Name):
            parts.append(current.id)
            return '.'.join(reversed(parts))
        return None
    if (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == 'getattr'
        and len(node.args) >= 2
        and isinstance(node.args[1], ast.Constant)
        and isinstance(node.args[1].value, str)
    ):
        base = _expr_to_str(node.args[0])
        if base:
            return f"{base}.{node.args[1].value}"
    return None


def _literal_string(node: ast.AST) -> Optional[str]:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    return None


def _literal_int(node: ast.AST) -> Optional[int]:
    if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
        try:
            return int(node.value)
        except Exception:
            return None
    return None


def analyze_python_file(py_path: Path) -> NodeIR | None:
    src = py_path.read_text(encoding='utf-8')
    try:
        tree = ast.parse(src)
    except SyntaxError:
        return None

    has_rospy = any(_is_rospy_import(n) for n in tree.body)
    if not has_rospy:
        return None

    node_ir = NodeIR(name=py_path.stem, file=str(py_path))

    class Visitor(ast.NodeVisitor):
        def visit_Call(self, n: ast.Call):
            func_name = _expr_to_str(n.func)
            try:
                if func_name == 'rospy.init_node' and n.args:
                    name = _literal_string(n.args[0])
                    if name:
                        node_ir.name = name
                elif func_name == 'rospy.Publisher' and len(n.args) >= 2:
                    topic = _literal_string(n.args[0]) or ''
                    msg_type = _expr_to_str(n.args[1]) or ''
                    queue_size = None
                    latched = None
                    for kw in n.keywords or []:
                        if kw.arg == 'queue_size':
                            qs = _literal_int(kw.value)
                            if qs is not None:
                                queue_size = qs
                        if kw.arg == 'latch' and isinstance(kw.value, ast.Constant) and isinstance(kw.value.value, bool):
                            latched = kw.value.value
                    node_ir.pubs.append(
                        TopicIR(topic=topic, type=msg_type, queue_size=queue_size, latched=latched)
                    )
                elif func_name == 'rospy.Subscriber' and len(n.args) >= 3:
                    topic = _literal_string(n.args[0]) or ''
                    msg_type = _expr_to_str(n.args[1]) or ''
                    callback = _expr_to_str(n.args[2]) or None
                    queue_size = None
                    for kw in n.keywords or []:
                        if kw.arg == 'queue_size':
                            qs = _literal_int(kw.value)
                            if qs is not None:
                                queue_size = qs
                    node_ir.subs.append(
                        TopicIR(topic=topic, type=msg_type, callback=callback, queue_size=queue_size)
                    )
            finally:
                self.generic_visit(n)

    Visitor().visit(tree)
    return node_ir


def analyze_python_sources(pkg_path: Path) -> List[NodeIR]:
    nodes: List[NodeIR] = []
    for py in list(pkg_path.glob('*.py')) + list((pkg_path / 'scripts').glob('*.py')):
        ir = analyze_python_file(py)
        if ir:
            nodes.append(ir)
    return nodes

