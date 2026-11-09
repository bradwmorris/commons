"""Refuse an incomplete distribution while the product tool package is absent."""

from pathlib import Path

from hatchling.builders.hooks.plugin.interface import BuildHookInterface


class CustomBuildHook(BuildHookInterface):
    def initialize(self, version, build_data):
        required = ("__init__.py", "commons_search.py", "commons_read.py", "commons_write.py")
        if any(not (Path(self.root) / "tools" / name).is_file() for name in required):
            raise RuntimeError("Cannot package Commons MCP without the three product tools and tools/__init__.py")
