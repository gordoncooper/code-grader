#!/usr/bin/env python3
"""gradekit: companion tool for the Code Grading Suite. `python3 tools/gradekit.py --help` lists the commands.

The engine is the gradekit_core package beside this file, one module per area (gradekit_core/__init__.py lists them
in dependency order). This file is the entry point and the facade: it loads that package and re-exports every name, so
`python3 tools/gradekit.py`, `import gradekit` and the website's `gradekit.web_api` work as before.

Python 3.11+; standard library only.
"""
import hashlib
import importlib.util
import sys
from pathlib import Path


def _load_core():
    """The package beside this file, under a name of its own, so two copies of the kit (say, the source and a built
    website) can run in one process without sharing modules."""
    here = Path(__file__).resolve().parent / "gradekit_core"
    name = "gradekit_core_" + hashlib.sha256(str(here).encode()).hexdigest()[:12]
    if name not in sys.modules:
        spec = importlib.util.spec_from_file_location(name, here / "__init__.py", submodule_search_locations=[str(here)])
        module = importlib.util.module_from_spec(spec)
        sys.modules[name] = module
        try:
            spec.loader.exec_module(module)
        except BaseException:
            for key in [k for k in sys.modules if k == name or k.startswith(name + ".")]:
                del sys.modules[key]
            raise
    return sys.modules[name]


core = _load_core()
for _name in core.MODULES:   # gradekit.<name> for every name in the engine
    globals().update({k: v for k, v in vars(getattr(core, _name)).items() if not k.startswith("__")})
del _name


if __name__ == "__main__":
    try:  # behave like a normal CLI when piped into `head` etc. (only as a script: never change a host process)
        import signal
        signal.signal(signal.SIGPIPE, signal.SIG_DFL)
    except (AttributeError, ValueError):
        pass
    sys.exit(core.cli.main())
