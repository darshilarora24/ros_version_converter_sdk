from __future__ import annotations

import ast
from pathlib import Path
from typing import List

from sdk.ir.model import NodeIR, TopicIR


def _is_rospy_import(node: ast.AST) -> bool:
    if isinstance(node, ast.Import):
        return any(n.name == 'rospy' for n in node.names)
    if isinstance(node, ast.ImportFrom):
        return node.module == 'rospy'
    return False


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
            # rospy.Publisher('topic', Type, ...)
            try:
                if isinstance(n.func, ast.Attribute) and isinstance(n.func.value, ast.Name) and n.func.value.id == 'rospy':
                    if n.func.attr == 'Publisher' and len(n.args) >= 2:
                        topic = ''
                        if isinstance(n.args[0], ast.Constant) and isinstance(n.args[0].value, str):
                            topic = n.args[0].value
                        msg_type = ''
                        if isinstance(n.args[1], ast.Name):
                            msg_type = n.args[1].id
                        queue_size = None
                        latched = None
                        for kw in n.keywords or []:
                            if kw.arg == 'queue_size' and isinstance(kw.value, ast.Constant) and isinstance(kw.value.value, (int, float)):
                                try:
                                    queue_size = int(kw.value.value)
                                except Exception:
                                    pass
                            if kw.arg == 'latch' and isinstance(kw.value, ast.Constant) and isinstance(kw.value.value, bool):
                                latched = bool(kw.value.value)
                        node_ir.pubs.append(TopicIR(topic=topic, type=msg_type, queue_size=queue_size, latched=latched))
                    elif n.func.attr == 'Subscriber' and len(n.args) >= 2:
                        topic = ''
                        if isinstance(n.args[0], ast.Constant) and isinstance(n.args[0].value, str):
                            topic = n.args[0].value
                        msg_type = ''
                        if isinstance(n.args[1], ast.Name):
                            msg_type = n.args[1].id
                        cb = None
                        if len(n.args) >= 3:
                            if isinstance(n.args[2], ast.Name):
                                cb = n.args[2].id
                            elif isinstance(n.args[2], ast.Attribute):
                                # Simple attr like self.cb or module.cb
                                cb = n.args[2].attr
                        queue_size = None
                        for kw in n.keywords or []:
                            if kw.arg == 'queue_size' and isinstance(kw.value, ast.Constant) and isinstance(kw.value.value, (int, float)):
                                try:
                                    queue_size = int(kw.value.value)
                                except Exception:
                                    pass
                        node_ir.subs.append(TopicIR(topic=topic, type=msg_type, callback=cb, queue_size=queue_size))
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
