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


class TestCLICommands(unittest.TestCase):
    def setUp(self):
        self.tmpdir = Path(tempfile.mkdtemp(prefix="ros_migrate_test_"))

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_report_and_check(self):
        # cmd_check should fail for missing package.xml
        class A: pass
        args = A(); args.path = str(self.tmpdir)
        rc = cmd_check(args)
        self.assertEqual(rc, 1)

        # cmd_report should write the report file
        args = A(); args.path = str(self.tmpdir)
        rc = cmd_report(args)
        self.assertEqual(rc, 0)
        self.assertTrue((self.tmpdir / "ros_migrate_report.txt").exists())

    def test_launch_generator(self):
        # Create a minimal roslaunch file
        launch_xml = self.tmpdir / "simple.launch"
        launch_xml.write_text(
            """
<launch>
  <node pkg="demo_pkg" type="demo_node" name="demo"/>
</launch>
            """.strip(),
            encoding="utf-8",
        )
        out_dir = self.tmpdir / "out_pkg"
        out_dir.mkdir(parents=True, exist_ok=True)

        class A: pass
        args = A(); args.launch = str(launch_xml); args.out = str(out_dir)
        rc = cmd_launch(args)
        self.assertEqual(rc, 0)
        # Expect generated .launch.py
        out_file = out_dir / "simple.launch.py"
        self.assertTrue(out_file.exists())
        text = out_file.read_text(encoding="utf-8")
        self.assertIn("LaunchDescription", text)
        self.assertIn("Node(", text)

    def test_convert_and_analyze(self):
        # Create a fake ROS1 package with package.xml and a rospy script
        pkg = self.tmpdir / "my_pkg"
        pkg.mkdir()
        (pkg / "package.xml").write_text(
            """
<?xml version="1.0"?>
<package format="2">
  <name>my_pkg</name>
  <version>0.0.0</version>
  <description>test pkg</description>
  <maintainer email="a@b.c">A</maintainer>
  <license>MIT</license>
  <buildtool_depend>catkin</buildtool_depend>
  <depend>std_msgs</depend>
</package>
            """.strip(),
            encoding="utf-8",
        )
        scripts = pkg / "scripts"
        scripts.mkdir()
        (scripts / "talker.py").write_text(
            """
#!/usr/bin/env python3
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
            """.strip(),
            encoding="utf-8",
        )

        # Convert into ROS2 skeleton
        out_ws = self.tmpdir / "out_ws"
        class C: pass
        args = C(); args.path = str(pkg); args.out = str(out_ws); args.lang = "py"
        rc = cmd_convert(args)
        self.assertEqual(rc, 0)
        # Check generated structure
        ros2_pkg = out_ws / "my_pkg_ros2"
        self.assertTrue((ros2_pkg / "package.xml").exists())
        self.assertTrue((ros2_pkg / "setup.cfg").exists())
        self.assertTrue((ros2_pkg / "pyproject.toml").exists())
        # Module exists and contains transformed/copied script
        self.assertTrue((ros2_pkg / "my_pkg").is_dir())
        generated_scripts = list((ros2_pkg / "my_pkg").glob("*.py"))
        self.assertTrue(generated_scripts)

        # Analyze the original package
        class A: pass
        args = A(); args.path = str(pkg)
        rc = cmd_analyze(args)
        self.assertEqual(rc, 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)

