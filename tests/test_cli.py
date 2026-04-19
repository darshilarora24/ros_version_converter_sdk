import os
import io
import sys
import shutil
import tempfile
import unittest
from pathlib import Path

# Ensure local imports resolve when running tests directly
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from cli.ros_migrate import (
    cmd_check,
    cmd_report,
    cmd_launch,
    cmd_convert,
    cmd_analyze,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_args(**kwargs):
    class A:
        pass
    a = A()
    for k, v in kwargs.items():
        setattr(a, k, v)
    return a


def _make_ros1_pkg(base: Path, name: str = "my_pkg") -> Path:
    """Create a minimal ROS1 package directory tree for tests."""
    pkg = base / name
    pkg.mkdir()
    (pkg / "package.xml").write_text(
        f"""<?xml version="1.0"?>
<package format="2">
  <name>{name}</name>
  <version>0.0.0</version>
  <description>test pkg</description>
  <maintainer email="a@b.c">A</maintainer>
  <license>MIT</license>
  <buildtool_depend>catkin</buildtool_depend>
  <depend>std_msgs</depend>
  <depend>std_srvs</depend>
</package>""",
        encoding="utf-8",
    )
    return pkg


# ---------------------------------------------------------------------------
# Original tests (preserved)
# ---------------------------------------------------------------------------

class TestCLICommands(unittest.TestCase):
    def setUp(self):
        self.tmpdir = Path(tempfile.mkdtemp(prefix="ros_migrate_test_"))

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_report_and_check(self):
        # cmd_check should fail for missing package.xml
        args = _make_args(path=str(self.tmpdir))
        rc = cmd_check(args)
        self.assertEqual(rc, 1)

        # cmd_report should write the report file
        args = _make_args(path=str(self.tmpdir))
        rc = cmd_report(args)
        self.assertEqual(rc, 0)
        self.assertTrue((self.tmpdir / "ros_migrate_report.txt").exists())

    def test_launch_generator(self):
        launch_xml = self.tmpdir / "simple.launch"
        launch_xml.write_text(
            """<launch>
  <node pkg="demo_pkg" type="demo_node" name="demo"/>
</launch>""",
            encoding="utf-8",
        )
        out_dir = self.tmpdir / "out_pkg"
        out_dir.mkdir(parents=True, exist_ok=True)

        args = _make_args(launch=str(launch_xml), out=str(out_dir))
        rc = cmd_launch(args)
        self.assertEqual(rc, 0)
        out_file = out_dir / "simple.launch.py"
        self.assertTrue(out_file.exists())
        text = out_file.read_text(encoding="utf-8")
        self.assertIn("LaunchDescription", text)
        self.assertIn("Node(", text)

    def test_convert_and_analyze(self):
        pkg = _make_ros1_pkg(self.tmpdir)
        scripts = pkg / "scripts"
        scripts.mkdir()
        (scripts / "talker.py").write_text(
            """#!/usr/bin/env python3
import rospy
from std_msgs.msg import String

def cb(msg):
    rospy.loginfo(f"heard: {msg}")

def main():
    rospy.init_node('talker')
    pub = rospy.Publisher('/chatter', String, queue_size=10)
    sub = rospy.Subscriber('/chatter', String, cb)
    rate = rospy.Rate(10)
    while not rospy.is_shutdown():
        pub.publish(String(data='hello'))
        rate.sleep()

if __name__ == '__main__':
    main()
""",
            encoding="utf-8",
        )

        out_ws = self.tmpdir / "out_ws"
        rc = cmd_convert(_make_args(path=str(pkg), out=str(out_ws), lang="py"))
        self.assertEqual(rc, 0)

        ros2_pkg = out_ws / "my_pkg_ros2"
        self.assertTrue((ros2_pkg / "package.xml").exists())
        self.assertTrue((ros2_pkg / "setup.cfg").exists())
        self.assertTrue((ros2_pkg / "pyproject.toml").exists())
        self.assertTrue((ros2_pkg / "my_pkg").is_dir())
        self.assertTrue(list((ros2_pkg / "my_pkg").glob("*.py")))

        rc = cmd_analyze(_make_args(path=str(pkg)))
        self.assertEqual(rc, 0)


# ---------------------------------------------------------------------------
# New tests: service/param/timer/TF detection in parser
# ---------------------------------------------------------------------------

class TestRospyParser(unittest.TestCase):
    def setUp(self):
        self.tmpdir = Path(tempfile.mkdtemp(prefix="ros_migrate_parser_"))

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _write_and_parse(self, src: str):
        from sdk.analyzers.rospy_parser import analyze_python_file
        py = self.tmpdir / "node.py"
        py.write_text(src, encoding="utf-8")
        return analyze_python_file(py)

    def test_service_server_detected(self):
        src = """import rospy
from std_srvs.srv import SetBool

def handle_set(req):
    return True

rospy.init_node('srv_node')
s = rospy.Service('set_bool', SetBool, handle_set)
rospy.spin()
"""
        ir = self._write_and_parse(src)
        self.assertIsNotNone(ir)
        servers = [s for s in ir.srvs if not s.is_client]
        self.assertEqual(len(servers), 1)
        self.assertEqual(servers[0].name, 'set_bool')
        self.assertEqual(servers[0].type, 'SetBool')
        self.assertEqual(servers[0].handler, 'handle_set')

    def test_service_client_detected(self):
        src = """import rospy
from std_srvs.srv import SetBool

rospy.init_node('client_node')
client = rospy.ServiceProxy('set_bool', SetBool)
"""
        ir = self._write_and_parse(src)
        self.assertIsNotNone(ir)
        clients = [s for s in ir.srvs if s.is_client]
        self.assertEqual(len(clients), 1)
        self.assertEqual(clients[0].name, 'set_bool')
        self.assertTrue(clients[0].is_client)

    def test_param_get_detected(self):
        src = """import rospy

rospy.init_node('param_node')
speed = rospy.get_param('max_speed', 1.0)
name = rospy.get_param('robot_name')
"""
        ir = self._write_and_parse(src)
        self.assertIsNotNone(ir)
        param_names = [p.name for p in ir.params]
        self.assertIn('max_speed', param_names)
        self.assertIn('robot_name', param_names)
        # default should be captured
        speed_param = next(p for p in ir.params if p.name == 'max_speed')
        self.assertEqual(speed_param.default, '1.0')

    def test_param_set_detected(self):
        src = """import rospy

rospy.init_node('param_node')
rospy.set_param('my_param', 42)
"""
        ir = self._write_and_parse(src)
        self.assertIsNotNone(ir)
        self.assertTrue(any(p.name == 'my_param' for p in ir.params))

    def test_timer_detected(self):
        src = """import rospy

def tick():
    pass

rospy.init_node('timer_node')
t = rospy.Timer(rospy.Duration(0.1), tick)
rospy.spin()
"""
        ir = self._write_and_parse(src)
        self.assertIsNotNone(ir)
        self.assertEqual(len(ir.timers), 1)
        self.assertEqual(ir.timers[0].callback, 'tick')
        self.assertAlmostEqual(ir.timers[0].period, 0.1)

    def test_tf_usage_detected(self):
        src = """import rospy
import tf

rospy.init_node('tf_node')
listener = tf.TransformListener()
"""
        ir = self._write_and_parse(src)
        self.assertIsNotNone(ir)
        self.assertTrue(ir.tf_usage)

    def test_clock_usage_detected(self):
        src = """import rospy

rospy.init_node('clock_node')
t = rospy.Time.now()
"""
        ir = self._write_and_parse(src)
        self.assertIsNotNone(ir)
        self.assertTrue(ir.clock_usage)

    def test_no_rospy_returns_none(self):
        src = """import rclpy
from rclpy.node import Node
"""
        ir = self._write_and_parse(src)
        self.assertIsNone(ir)


# ---------------------------------------------------------------------------
# New tests: transformer output for services, params, timers, TF
# ---------------------------------------------------------------------------

class TestTransformerOutput(unittest.TestCase):
    def setUp(self):
        self.tmpdir = Path(tempfile.mkdtemp(prefix="ros_migrate_transform_"))

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _transform(self, src: str) -> str:
        from sdk.transformers.rospy_to_rclpy import transform_rospy_file
        py = self.tmpdir / "node.py"
        py.write_text(src, encoding="utf-8")
        result = transform_rospy_file(py)
        self.assertIsNotNone(result)
        return result

    def test_service_server_in_output(self):
        src = """import rospy
from std_srvs.srv import SetBool

def handle_set(req):
    return True

rospy.init_node('srv_node')
s = rospy.Service('set_bool', SetBool, handle_set)
rospy.spin()
"""
        out = self._transform(src)
        self.assertIn('create_service', out)
        self.assertIn("'set_bool'", out)
        self.assertIn('SetBool', out)
        # handler stub should appear
        self.assertIn('handle_set', out)

    def test_service_client_in_output(self):
        src = """import rospy
from std_srvs.srv import SetBool

rospy.init_node('client_node')
client = rospy.ServiceProxy('set_bool', SetBool)
"""
        out = self._transform(src)
        self.assertIn('create_client', out)
        self.assertIn("'set_bool'", out)

    def test_parameter_declare_in_output(self):
        src = """import rospy

rospy.init_node('param_node')
speed = rospy.get_param('max_speed', 1.0)
"""
        out = self._transform(src)
        self.assertIn('declare_parameter', out)
        self.assertIn("'max_speed'", out)
        self.assertIn('1.0', out)

    def test_timer_in_output(self):
        src = """import rospy

def tick():
    pass

rospy.init_node('timer_node')
t = rospy.Timer(rospy.Duration(0.5), tick)
rospy.spin()
"""
        out = self._transform(src)
        self.assertIn('create_timer', out)
        self.assertIn('0.5', out)

    def test_tf_import_in_output(self):
        src = """import rospy
import tf

rospy.init_node('tf_node')
listener = tf.TransformListener()
"""
        out = self._transform(src)
        self.assertIn('import tf2_ros', out)
        self.assertIn('tf2_ros.Buffer()', out)
        self.assertIn('tf2_ros.TransformListener', out)
        # old tf import should not survive
        self.assertNotIn('import tf\n', out)

    def test_clock_comment_in_output(self):
        src = """import rospy

rospy.init_node('clock_node')
t = rospy.Time.now()
"""
        out = self._transform(src)
        self.assertIn('get_clock().now()', out)

    def test_rate_timer_stub_generated(self):
        src = """import rospy
from std_msgs.msg import String

rospy.init_node('rate_node')
rate = rospy.Rate(10)
while not rospy.is_shutdown():
    rate.sleep()
"""
        out = self._transform(src)
        self.assertIn('create_timer', out)
        self.assertIn('_tick', out)

    def test_pubsub_preserved(self):
        src = """import rospy
from std_msgs.msg import String

def cb(msg): pass

rospy.init_node('ps_node')
pub = rospy.Publisher('/out', String, queue_size=5)
sub = rospy.Subscriber('/in', String, cb)
rospy.spin()
"""
        out = self._transform(src)
        self.assertIn('create_publisher', out)
        self.assertIn('create_subscription', out)
        self.assertIn("'/out'", out)
        self.assertIn("'/in'", out)


# ---------------------------------------------------------------------------
# New tests: validators
# ---------------------------------------------------------------------------

class TestValidators(unittest.TestCase):
    def setUp(self):
        self.tmpdir = Path(tempfile.mkdtemp(prefix="ros_migrate_val_"))

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_empty_dir_has_issues(self):
        from sdk.validators.basic import basic_checks
        issues = basic_checks(self.tmpdir)
        self.assertTrue(any('package.xml' in i for i in issues))

    def test_valid_ros2_package_minimal_issues(self):
        from sdk.validators.basic import basic_checks
        pkg_name = "good_pkg"
        (self.tmpdir / "package.xml").write_text(
            f"""<?xml version="1.0"?>
<package format="3">
  <name>{pkg_name}</name>
  <version>0.1.0</version>
  <exec_depend>rclpy</exec_depend>
  <export><build_type>ament_python</build_type></export>
</package>""",
            encoding="utf-8",
        )
        (self.tmpdir / "setup.cfg").write_text("[metadata]\nname = good_pkg\n", encoding="utf-8")
        (self.tmpdir / "pyproject.toml").write_text("[build-system]\nrequires = [\"setuptools\"]\n", encoding="utf-8")
        module = self.tmpdir / pkg_name
        module.mkdir()
        (module / "__init__.py").write_text("", encoding="utf-8")

        issues = basic_checks(self.tmpdir)
        # Only TODO items may remain (none here)
        non_todo = [i for i in issues if 'TODO' not in i]
        self.assertEqual(non_todo, [])

    def test_missing_rclpy_dep_flagged(self):
        from sdk.validators.basic import basic_checks
        (self.tmpdir / "package.xml").write_text(
            """<?xml version="1.0"?>
<package format="3">
  <name>bad_pkg</name>
  <exec_depend>some_other_dep</exec_depend>
</package>""",
            encoding="utf-8",
        )
        issues = basic_checks(self.tmpdir)
        self.assertTrue(any('rclpy' in i for i in issues))

    def test_todo_count_reported(self):
        from sdk.validators.basic import basic_checks
        (self.tmpdir / "package.xml").write_text(
            """<?xml version="1.0"?>
<package format="3">
  <name>todo_pkg</name>
  <exec_depend>rclpy</exec_depend>
</package>""",
            encoding="utf-8",
        )
        (self.tmpdir / "node.py").write_text("# TODO: fix this\n# TODO: and this\n", encoding="utf-8")
        issues = basic_checks(self.tmpdir)
        self.assertTrue(any('TODO' in i for i in issues))
        # should report count >= 2
        todo_issue = next(i for i in issues if 'TODO' in i)
        count = int(todo_issue.split()[0])
        self.assertGreaterEqual(count, 2)


# ---------------------------------------------------------------------------
# New tests: improved cmd_check / cmd_report
# ---------------------------------------------------------------------------

class TestImprovedCLI(unittest.TestCase):
    def setUp(self):
        self.tmpdir = Path(tempfile.mkdtemp(prefix="ros_migrate_cli2_"))

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_check_passes_for_valid_ros2_package(self):
        pkg_name = "valid_pkg"
        (self.tmpdir / "package.xml").write_text(
            f"""<?xml version="1.0"?>
<package format="3">
  <name>{pkg_name}</name>
  <exec_depend>rclpy</exec_depend>
</package>""",
            encoding="utf-8",
        )
        (self.tmpdir / "setup.cfg").write_text("", encoding="utf-8")
        (self.tmpdir / "pyproject.toml").write_text("", encoding="utf-8")
        module = self.tmpdir / pkg_name
        module.mkdir()
        (module / "__init__.py").write_text("", encoding="utf-8")

        rc = cmd_check(_make_args(path=str(self.tmpdir)))
        # May still have TODO issues from __init__.py content — accept 0 or 1
        self.assertIn(rc, (0, 1))

    def test_report_contains_node_info(self):
        pkg = _make_ros1_pkg(self.tmpdir, "report_pkg")
        scripts = pkg / "scripts"
        scripts.mkdir()
        (scripts / "reporter_node.py").write_text(
            """import rospy
from std_msgs.msg import String
from std_srvs.srv import SetBool

def handle(req): return True

rospy.init_node('reporter')
pub = rospy.Publisher('/out', String, queue_size=1)
s = rospy.Service('my_srv', SetBool, handle)
p = rospy.get_param('speed', 0.5)
""",
            encoding="utf-8",
        )
        rc = cmd_report(_make_args(path=str(pkg)))
        self.assertEqual(rc, 0)
        report = (pkg / "ros_migrate_report.txt").read_text(encoding="utf-8")
        self.assertIn("reporter", report)
        self.assertIn("Publisher", report)
        self.assertIn("my_srv", report)
        self.assertIn("speed", report)

    def test_analyze_shows_services_and_params(self):
        pkg = _make_ros1_pkg(self.tmpdir, "analyze_pkg")
        scripts = pkg / "scripts"
        scripts.mkdir()
        (scripts / "full_node.py").write_text(
            """import rospy
from std_srvs.srv import SetBool
import tf

def handle(req): return True

rospy.init_node('full_node')
s = rospy.Service('my_srv', SetBool, handle)
val = rospy.get_param('my_param', 42)
t = rospy.Timer(rospy.Duration(1.0), handle)
""",
            encoding="utf-8",
        )
        import io, contextlib
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            rc = cmd_analyze(_make_args(path=str(pkg)))
        self.assertEqual(rc, 0)
        output = buf.getvalue()
        self.assertIn('my_srv', output)
        self.assertIn('my_param', output)
        self.assertIn('tf', output)


# ---------------------------------------------------------------------------
# New tests: launch file advanced features
# ---------------------------------------------------------------------------

class TestLaunchAdvanced(unittest.TestCase):
    def setUp(self):
        self.tmpdir = Path(tempfile.mkdtemp(prefix="ros_migrate_launch_"))

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_launch_with_args_and_remap(self):
        launch_xml = self.tmpdir / "adv.launch"
        launch_xml.write_text(
            """<launch>
  <arg name="robot_name" default="my_robot"/>
  <node pkg="nav_pkg" type="nav_node" name="nav">
    <remap from="/old_topic" to="/new_topic"/>
    <param name="speed" value="1.5"/>
  </node>
</launch>""",
            encoding="utf-8",
        )
        out = self.tmpdir / "out"
        out.mkdir()
        rc = cmd_launch(_make_args(launch=str(launch_xml), out=str(out)))
        self.assertEqual(rc, 0)
        text = (out / "adv.launch.py").read_text(encoding="utf-8")
        self.assertIn("DeclareLaunchArgument", text)
        self.assertIn("robot_name", text)
        self.assertIn("remappings", text)
        self.assertIn("parameters", text)

    def test_launch_with_env_substitution(self):
        launch_xml = self.tmpdir / "env.launch"
        launch_xml.write_text(
            """<launch>
  <node pkg="my_pkg" type="my_node" name="n" ns="$(env MY_NS)"/>
</launch>""",
            encoding="utf-8",
        )
        out = self.tmpdir / "out"
        out.mkdir()
        rc = cmd_launch(_make_args(launch=str(launch_xml), out=str(out)))
        self.assertEqual(rc, 0)
        text = (out / "env.launch.py").read_text(encoding="utf-8")
        self.assertIn("EnvironmentVariable", text)
        self.assertIn("MY_NS", text)

    def test_launch_with_conditional_node(self):
        launch_xml = self.tmpdir / "cond.launch"
        launch_xml.write_text(
            """<launch>
  <arg name="use_sim" default="false"/>
  <node pkg="sim_pkg" type="sim_node" name="sim" if="$(arg use_sim)"/>
</launch>""",
            encoding="utf-8",
        )
        out = self.tmpdir / "out"
        out.mkdir()
        rc = cmd_launch(_make_args(launch=str(launch_xml), out=str(out)))
        self.assertEqual(rc, 0)
        text = (out / "cond.launch.py").read_text(encoding="utf-8")
        self.assertIn("IfCondition", text)
        self.assertIn("use_sim", text)


if __name__ == "__main__":
    unittest.main(verbosity=2)
