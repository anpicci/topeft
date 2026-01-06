import importlib


MODULES = [
    "topeft.modules.logging_config",
    "analysis.topeft_run2.logging_utils",
    "analysis.topeft_run2.run_analysis_helpers",
]


def test_lightweight_imports() -> None:
    for module_name in MODULES:
        importlib.import_module(module_name)
