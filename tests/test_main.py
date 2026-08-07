"""Guards the one invariant coderoot_mcp.__main__ exists to protect: that
importing the module never constructs Settings() (which raises ConfigError
when unconfigured). A module-level `create_mcp()`/server construction would
make merely importing this module crash on an unconfigured machine -- the
exact defect that cost the sibling Assessor repo a fix round."""
import importlib
import sys


def test_importing_main_has_no_side_effects_when_unconfigured(monkeypatch):
    monkeypatch.delenv("CODEROOT_API_URL", raising=False)
    monkeypatch.delenv("CODEROOT_API_TOKEN", raising=False)
    # Force a fresh import even if some earlier test already cached the
    # module, so the module body actually executes under this environment.
    sys.modules.pop("coderoot_mcp.__main__", None)
    importlib.import_module("coderoot_mcp.__main__")
