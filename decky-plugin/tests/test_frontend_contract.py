"""Every backend call the frontend makes must exist on the Decky Plugin class and in the bridge.

Run from the repo root: python3 -m unittest discover -s decky-plugin/tests
"""

import os
import re
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
PLUGIN = os.path.dirname(HERE)


def read(*parts):
    with open(os.path.join(PLUGIN, *parts), encoding="utf-8") as f:
        return f.read()


class FrontendContractTest(unittest.TestCase):
    def test_every_callable_has_a_plugin_method(self):
        calls = set(re.findall(r'callable<[^>]*>\(\s*"(\w+)"\s*\)', read("src", "index.tsx")))
        self.assertIn("lite_verify", calls)
        methods = set(re.findall(r"^\s+async def (\w+)\(", read("main.py"), re.M))
        self.assertEqual(sorted(calls - methods), [], "frontend calls without a main.py method")

    def test_plugin_lite_methods_reach_bridge_commands(self):
        main = read("main.py")
        bridge = read("py_modules", "helixsr_bridge.py")
        for cmd in re.findall(r'self\._call\("(\w+)"', main):
            self.assertRegex(bridge, r'"%s":\s*lambda' % cmd, f"bridge has no {cmd} command")


if __name__ == "__main__":
    unittest.main()
