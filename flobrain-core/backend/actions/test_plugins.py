from django.test import TestCase

from actions import registry
from actions.plugins import handler, register_tool
from actions.service import ActionDenied


class PluginRegistryTests(TestCase):
    def tearDown(self):
        registry.TOOLS.pop("test.echo", None)
        from actions import plugins

        plugins._HANDLERS.pop("test.echo", None)

    def test_register_and_dispatch(self):
        spec = {"perm_key": "ai.use", "risk": "write", "label": "Echo", "description": "Echo", "schema": {"type": "object"}}
        register_tool("test.echo", spec, check=lambda u, o, a: "Echo it", execute=lambda u, o, a: {"echo": a})
        self.assertIn("test.echo", registry.TOOLS)
        self.assertEqual(handler("test.echo").execute(None, None, {"x": 1}), {"echo": {"x": 1}})

    def test_builtin_cannot_be_replaced(self):
        spec = dict(registry.TOOLS["tasks.create"])
        with self.assertRaises(ValueError):
            register_tool("tasks.create", spec, check=lambda *a: "", execute=lambda *a: {})

    def test_missing_fields_rejected(self):
        with self.assertRaises(ValueError):
            register_tool("test.echo", {"perm_key": "ai.use"}, check=lambda *a: "", execute=lambda *a: {})
        self.assertIsNotNone(ActionDenied)
