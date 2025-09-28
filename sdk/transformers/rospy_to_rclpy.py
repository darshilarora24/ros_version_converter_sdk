from __future__ import annotations

import ast
import re
import shutil
from pathlib import Path
from typing import List, Optional

from sdk.analyzers.rospy_parser import analyze_python_file
from sdk.ir.model import NodeIR, PackageIR
from sdk.rules.loader import load_api_rules, load_qos_rules


PKG_XML_TEMPLATE = """<?xml version="1.0"?>
<package format="3">
  <name>{name}</name>
  <version>0.1.0</version>
  <description>Auto-converted ROS1 -> ROS2 package (skeleton)</description>
  <maintainer email="todo@example.com">TODO</maintainer>
  <license>TODO</license>
  <buildtool_depend>ament_cmake</buildtool_depend>
  <buildtool_depend>ament_python</buildtool_depend>
  <exec_depend>rclpy</exec_depend>
  <exec_depend>rosidl_default_runtime</exec_depend>
  {msg_deps}
  <export>
    <build_type>ament_python</build_type>
  </export>
</package>
"""


SETUP_CFG_TEMPLATE = """[metadata]
name = {name}
version = 0.1.0

[options]
packages = find:
install_requires =
    rclpy
zip_safe = false

[options.entry_points]
console_scripts =
{entry_points}
"""


def _ros1_py_scripts(src: Path):
    yield from src.glob('*.py')
    scripts = src / 'scripts'
    if scripts.exists():
        yield from scripts.glob('*.py')


def convert_python_package_skeleton(src_pkg: Path, out_ws: Path, pkg: PackageIR) -> None:
    """
    Minimal skeleton converter for Python packages.

    - Creates a ROS 2 style package folder
    - Attempts a best-effort rospy -> rclpy rewrite for Python entry-points
    - Copies sources verbatim with a TODO header when automatic conversion fails

    NOTE: Manual polishing is still required; this produces a runnable starting point.
    """
    ros2_pkg_dir = out_ws / f"{pkg.name}_ros2"
    module_dir = ros2_pkg_dir / pkg.name
    launch_dir = ros2_pkg_dir / 'launch'
    config_dir = ros2_pkg_dir / 'config'

    for directory in (module_dir, launch_dir, config_dir):
        directory.mkdir(parents=True, exist_ok=True)

    init_py = module_dir / '__init__.py'
    if not init_py.exists():
        init_py.write_text('# Auto-generated package marker.\n', encoding='utf-8')

    # Copy msgs/srvs/actions if they exist
    for iface in ('msg', 'srv', 'action'):
        src_dir = src_pkg / iface
        if src_dir.exists():
            shutil.copytree(src_dir, ros2_pkg_dir / iface, dirs_exist_ok=True)

    entries: List[str] = []
    for py in _ros1_py_scripts(src_pkg):
        if py.name == '__init__.py':
            dst_init = module_dir / py.name
            shutil.copy2(py, dst_init)
            continue
        rel_name = py.stem
        dst = module_dir / f"{rel_name}.py"
        transformed = transform_rospy_file(py)
        if transformed is None:
            text = py.read_text(encoding='utf-8')
            header = (
                "# AUTO-GENERATED SKELETON\n"
                "# TODO: convert rospy -> rclpy (manual follow-up required)\n\n"
            )
            content = header + text
        else:
            content = transformed
        dst.write_text(content, encoding='utf-8')
        if 'def main(' in content:
            entries.append(f"    {rel_name} = {pkg.name}.{rel_name}:main")

    # package.xml
    msg_deps = "".join([f"  <exec_depend>{dep}</exec_depend>\n" for dep in pkg.deps if dep.endswith('_msgs')])
    (ros2_pkg_dir / 'package.xml').write_text(
        PKG_XML_TEMPLATE.format(name=pkg.name, msg_deps=msg_deps), encoding='utf-8'
    )

    # setup.cfg with console_scripts
    entry_points = "\n".join(entries) if entries else ""
    (ros2_pkg_dir / 'setup.cfg').write_text(
        SETUP_CFG_TEMPLATE.format(name=pkg.name, entry_points=entry_points), encoding='utf-8'
    )

    # Minimal pyproject for editable installs if desired
    (ros2_pkg_dir / 'pyproject.toml').write_text(
        """[build-system]\nrequires = [\"setuptools\"]\nbuild-backend = \"setuptools.build_meta\"\n""",
        encoding='utf-8'
    )


def _dedupe_preserve_order(values: List[str]) -> List[str]:
    seen = set()
    out: List[str] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        out.append(value)
    return out


def _ensure_import(imports: List[str], statement: str, *, at_start: bool = False, after: Optional[str] = None) -> None:
    if statement in imports:
        return
    if after and after in imports:
        idx = imports.index(after) + 1
        imports.insert(idx, statement)
    elif at_start:
        imports.insert(0, statement)
    else:
        imports.append(statement)


def _collect_non_rospy_imports(src: str) -> List[str]:
    lines: List[str] = []
    try:
        tree = ast.parse(src)
    except SyntaxError:
        return lines
    for node in tree.body:
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            if isinstance(node, ast.Import):
                if any(alias.name == 'rospy' for alias in node.names):
                    continue
            if isinstance(node, ast.ImportFrom):
                if node.module == 'rospy' or (node.module and node.module.startswith('rospy.')):
                    continue
            segment = ast.get_source_segment(src, node)
            if segment:
                lines.append(segment.strip())
    return _dedupe_preserve_order(lines)


def _node_body_has_rospy_calls(node: ast.AST) -> bool:
    for child in ast.walk(node):
        if isinstance(child, ast.Attribute) and isinstance(child.value, ast.Name) and child.value.id == 'rospy':
            if child.attr in {'logdebug', 'loginfo', 'logwarn', 'logerr'}:
                continue
            return True
    return False


def _collect_defs(src: str, *, skip: Optional[List[str]] = None) -> List[str]:
    skip_names = set(skip or [])
    out: List[str] = []
    try:
        tree = ast.parse(src)
    except SyntaxError:
        return out
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            name = getattr(node, 'name', None)
            if name and name in skip_names:
                continue
            if _node_body_has_rospy_calls(node):
                continue
            segment = ast.get_source_segment(src, node)
            if segment:
                out.append(segment.rstrip())
    return out


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
    return None


def _find_init_node_name(src: str) -> Optional[str]:
    try:
        tree = ast.parse(src)
    except SyntaxError:
        return None
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            func_name = _expr_to_str(node.func)
            if func_name == 'rospy.init_node' and node.args:
                first = node.args[0]
                if isinstance(first, ast.Constant) and isinstance(first.value, str):
                    return first.value
    return None


_RATE_RE = re.compile(r"rospy\.Rate\((\d+(?:\.\d+)?)\)")


def _extract_rate_period(src: str) -> Optional[float]:
    match = _RATE_RE.search(src)
    if not match:
        return None
    try:
        hz = float(match.group(1))
        if hz <= 0:
            return None
        return round(1.0 / hz, 6)
    except Exception:
        return None


def _format_msg_type(type_name: str) -> tuple[str, Optional[str]]:
    if type_name:
        return type_name, None
    return 'TODO_MSG_TYPE', '# TODO: replace TODO_MSG_TYPE with the correct message type'


def _format_topic(topic: str) -> tuple[str, Optional[str]]:
    if topic:
        return repr(topic), None
    return repr('TODO_TOPIC'), '# TODO: replace TODO_TOPIC with the desired topic name'


def _format_callback(callback: Optional[str]) -> tuple[str, Optional[str]]:
    if callback:
        return callback, None
    return 'lambda msg: None', '# TODO: supply a migration-safe subscription callback'


def _rewrite_logging_in_text(src: str, logger_name: str) -> str:
    try:
        rules_dir = Path(__file__).resolve().parents[1] / 'rules'
        api = load_api_rules(rules_dir)
        logging_map = (api.get('logging') or {}) if isinstance(api, dict) else {}
    except Exception:
        logging_map = {}
    default_logger = f"rclpy.logging.get_logger({repr(logger_name)})"
    replacements = {
        'rospy.logdebug': logging_map.get('rospy.logdebug', f'{default_logger}.debug'),
        'rospy.loginfo': logging_map.get('rospy.loginfo', f'{default_logger}.info'),
        'rospy.logwarn': logging_map.get('rospy.logwarn', f'{default_logger}.warn'),
        'rospy.logerr': logging_map.get('rospy.logerr', f'{default_logger}.error'),
    }
    for original, replacement in replacements.items():
        if replacement.startswith('node.get_logger()'):
            replacement = default_logger + replacement[len('node.get_logger()'):]
        src = src.replace(original, replacement)
    return src


def transform_rospy_file(path: Path) -> Optional[str]:
    """Attempt a first-pass rospy -> rclpy transformation for simple pub/sub nodes."""
    src = path.read_text(encoding='utf-8')
    node_ir: Optional[NodeIR] = analyze_python_file(path)
    if node_ir is None:
        return None

    shebang = ''
    src_lines = src.splitlines()
    if src_lines and src_lines[0].startswith('#!'):
        shebang = src_lines[0].strip()

    node_name = _find_init_node_name(src) or node_ir.name or path.stem or 'migrated_node'
    logger_name = node_name or 'migrated_node'

    imports = _collect_non_rospy_imports(src)
    _ensure_import(imports, 'import rclpy', at_start=True)
    _ensure_import(imports, 'from rclpy.node import Node', after='import rclpy')
    if any(getattr(p, 'latched', None) for p in node_ir.pubs):
        _ensure_import(imports, 'from rclpy.qos import QoSProfile, QoSDurabilityPolicy')

    rewritten_src = _rewrite_logging_in_text(src, logger_name)
    defs_src = _collect_defs(rewritten_src, skip=['main'])

    rules_dir = Path(__file__).resolve().parents[1] / 'rules'
    try:
        api_rules = load_api_rules(rules_dir)
    except Exception:
        api_rules = {}
    try:
        qos_rules = load_qos_rules(rules_dir)
    except Exception:
        qos_rules = {}

    pubsub_rules = api_rules.get('pubsub') if isinstance(api_rules, dict) else {}
    publisher_method = (pubsub_rules or {}).get('publisher_method') or 'create_publisher'
    subscription_method = (pubsub_rules or {}).get('subscription_method') or 'create_subscription'
    qos_map = qos_rules.get('queue_to_qos') if isinstance(qos_rules, dict) else {}
    default_depth = (qos_map or {}).get('default_depth') or 10

    timer_period = _extract_rate_period(src)
    needs_timer_stub = timer_period is not None

    lines: List[str] = []
    if shebang:
        lines.append(shebang)
        lines.append('')
    lines.append('# AUTO-GENERATED BY ros_version_converter_sdk')
    lines.append(f'# Source: {path.name}')
    lines.append('# Review manually: complex rospy patterns may need additional migration work.')
    lines.append('')

    if imports:
        lines.extend(imports)
        lines.append('')
    else:
        lines.append('import rclpy')
        lines.append('from rclpy.node import Node')
        lines.append('')

    if defs_src:
        lines.extend(defs_src)
        lines.append('')

    lines.append('class MigratedNode(Node):')
    lines.append('    """Best-effort port of the original rospy node."""')
    lines.append('    def __init__(self) -> None:')
    lines.append(f"        super().__init__({repr(node_name)})")

    init_lines: List[str] = []

    if timer_period:
        init_lines.append('        # TODO: replace rospy.Rate loop with a real timer callback')
        init_lines.append(
            f'        self.timer = self.create_timer({timer_period}, getattr(self, "_tick", lambda: None))'
        )

    if node_ir.pubs:
        init_lines.append('        # Publishers')
        for index, pub in enumerate(node_ir.pubs):
            msg_expr, msg_comment = _format_msg_type(pub.type)
            topic_expr, topic_comment = _format_topic(pub.topic)
            notes = [comment for comment in (msg_comment, topic_comment) if comment]
            for note in notes:
                init_lines.append(f'        {note}')
            depth = pub.queue_size if getattr(pub, 'queue_size', None) else default_depth
            if getattr(pub, 'latched', None):
                init_lines.append(f'        qos_profile_{index} = QoSProfile(depth={depth})')
                init_lines.append(
                    f'        qos_profile_{index}.durability = QoSDurabilityPolicy.TRANSIENT_LOCAL'
                )
                init_lines.append(
                    f'        self.publisher_{index} = self.{publisher_method}({msg_expr}, {topic_expr}, qos_profile_{index})'
                )
            else:
                init_lines.append(
                    f'        self.publisher_{index} = self.{publisher_method}({msg_expr}, {topic_expr}, {depth})'
                )

    if node_ir.subs:
        init_lines.append('        # Subscriptions')
        for index, sub in enumerate(node_ir.subs):
            msg_expr, msg_comment = _format_msg_type(sub.type)
            topic_expr, topic_comment = _format_topic(sub.topic)
            cb_expr, cb_comment = _format_callback(sub.callback)
            notes = [comment for comment in (msg_comment, topic_comment, cb_comment) if comment]
            for note in notes:
                init_lines.append(f'        {note}')
            depth = sub.queue_size if getattr(sub, 'queue_size', None) else default_depth
            init_lines.append(
                f'        self.subscription_{index} = self.{subscription_method}({msg_expr}, {topic_expr}, {cb_expr}, {depth})'
            )

    if not init_lines:
        init_lines.append('        # TODO: port initialization logic from the original script')
        init_lines.append('        pass')
    else:
        if not any(line.strip() and not line.strip().startswith('#') for line in init_lines):
            init_lines.append('        pass')

    lines.extend(init_lines)

    if needs_timer_stub:
        lines.append('')
        lines.append('    def _tick(self) -> None:')
        lines.append('        # TODO: migrate work that ran inside the rospy.Rate loop')
        lines.append('        pass')

    lines.append('')
    lines.append('def main(args=None) -> None:')
    lines.append('    rclpy.init(args=args)')
    lines.append('    node = MigratedNode()')
    lines.append('    try:')
    lines.append('        rclpy.spin(node)')
    lines.append('    except KeyboardInterrupt:')
    lines.append("        node.get_logger().info('Shutting down (keyboard interrupt).')")
    lines.append('    finally:')
    lines.append('        node.destroy_node()')
    lines.append('        rclpy.shutdown()')
    lines.append('')
    lines.append("if __name__ == '__main__':")
    lines.append('    main()')

    return "\n".join(lines) + "\n"

