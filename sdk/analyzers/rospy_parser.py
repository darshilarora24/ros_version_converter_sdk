from __future__ import annotations

import ast
from pathlib import Path
from typing import List, Optional

from sdk.ir.model import NodeIR, ParamIR, ServiceIR, TimerIR, TopicIR


def _is_rospy_import(node: ast.AST) -> bool:
    if isinstance(node, ast.Import):
        return any(n.name == 'rospy' for n in node.names)
    if isinstance(node, ast.ImportFrom):
        return node.module == 'rospy'
    return False


def _is_tf_import(node: ast.AST) -> bool:
    if isinstance(node, ast.Import):
        return any(n.name in ('tf', 'tf2_ros', 'tf2_geometry_msgs', 'tf2_sensor_msgs') for n in node.names)
    if isinstance(node, ast.ImportFrom):
        return bool(node.module and (node.module.startswith('tf.') or node.module.startswith('tf2')))
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


def _literal_number(node: ast.AST) -> Optional[float]:
    if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
        try:
            return float(node.value)
        except Exception:
            return None
    return None


def _literal_int(node: ast.AST) -> Optional[int]:
    if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
        try:
            return int(node.value)
        except Exception:
            return None
    return None


def _extract_duration_seconds(node: ast.AST) -> Optional[float]:
    """Extract seconds from rospy.Duration(secs) or rospy.Duration(secs, nsecs) call."""
    if not isinstance(node, ast.Call):
        return None
    func = _expr_to_str(node.func)
    if func not in ('rospy.Duration', 'Duration'):
        return None
    if node.args:
        return _literal_number(node.args[0])
    for kw in node.keywords:
        if kw.arg in ('secs', 'nsecs'):
            val = _literal_number(kw.value)
            if val is not None and kw.arg == 'secs':
                return val
    return None


def _repr_default(node: ast.AST) -> Optional[str]:
    """Return a repr string for simple literal default values."""
    if isinstance(node, ast.Constant):
        return repr(node.value)
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.USub):
        inner = _literal_number(node.operand)
        if inner is not None:
            return repr(-inner)
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

    # Detect TF imports at module level
    if any(_is_tf_import(n) for n in tree.body):
        node_ir.tf_usage = True

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

                elif func_name == 'rospy.Service' and len(n.args) >= 2:
                    name = _literal_string(n.args[0]) or ''
                    srv_type = _expr_to_str(n.args[1]) or ''
                    handler = _expr_to_str(n.args[2]) if len(n.args) >= 3 else None
                    node_ir.srvs.append(
                        ServiceIR(name=name, type=srv_type, handler=handler, is_client=False)
                    )

                elif func_name == 'rospy.ServiceProxy' and len(n.args) >= 2:
                    name = _literal_string(n.args[0]) or ''
                    srv_type = _expr_to_str(n.args[1]) or ''
                    node_ir.srvs.append(
                        ServiceIR(name=name, type=srv_type, is_client=True)
                    )

                elif func_name in ('rospy.get_param', 'rospy.set_param') and n.args:
                    param_name = _literal_string(n.args[0]) or ''
                    if param_name and not any(p.name == param_name for p in node_ir.params):
                        default = None
                        if func_name == 'rospy.get_param' and len(n.args) >= 2:
                            default = _repr_default(n.args[1])
                        node_ir.params.append(ParamIR(name=param_name, default=default))

                elif func_name == 'rospy.Timer' and len(n.args) >= 2:
                    period = _extract_duration_seconds(n.args[0])
                    callback = _expr_to_str(n.args[1]) or None
                    if callback:
                        node_ir.timers.append(TimerIR(callback=callback, period=period))

                elif func_name in ('rospy.Time.now', 'rospy.get_rostime'):
                    node_ir.clock_usage = True

            finally:
                self.generic_visit(n)

    Visitor().visit(tree)
    return node_ir


def analyze_python_sources(pkg_path: Path) -> List[NodeIR]:
    nodes: List[NodeIR] = []
    candidates = list(pkg_path.glob('*.py'))
    scripts_dir = pkg_path / 'scripts'
    if scripts_dir.exists():
        candidates += list(scripts_dir.glob('*.py'))
    for py in candidates:
        ir = analyze_python_file(py)
        if ir:
            nodes.append(ir)
    return nodes
