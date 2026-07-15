import importlib.util
from pathlib import Path
from types import ModuleType


def load_module(name: str, relative_path: str) -> ModuleType:
    """Load a Python file as an importable module.

    Args:
        name: Module name to assign
        relative_path: Path relative to repo root (e.g., "bin/pr_fetcher.py")

    Returns:
        The loaded module object
    """
    # Resolve path relative to repo root (tests/ is one level down)
    repo_root = Path(__file__).parent.parent
    file_path = repo_root / relative_path

    spec = importlib.util.spec_from_file_location(name, file_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Could not load {file_path}")

    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module
