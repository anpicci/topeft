import ast
from pathlib import Path
from typing import Optional


def _find_class(tree: ast.AST, name: str) -> Optional[ast.ClassDef]:
    for node in tree.body:
        if isinstance(node, ast.ClassDef) and node.name == name:
            return node
    return None


def _find_method(class_node: ast.ClassDef, name: str) -> Optional[ast.FunctionDef]:
    for node in class_node.body:
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return node
    return None


def test_channel_label_path_is_modern():
    path = (
        Path(__file__).resolve().parents[1]
        / "analysis"
        / "topeft_run2"
        / "analysis_processor.py"
    )
    source = path.read_text(encoding="utf-8")
    tree = ast.parse(source)

    class_node = _find_class(tree, "AnalysisProcessor")
    assert class_node is not None, "AnalysisProcessor class not found"

    attr_names = {node.attr for node in ast.walk(class_node) if isinstance(node, ast.Attribute)}
    assert "_build_channel_names" not in attr_names, (
        "AnalysisProcessor should not reference _build_channel_names; "
        "use build_channel_label instead."
    )

    method = _find_method(class_node, "_fill_histograms_for_variation")
    assert method is not None, "_fill_histograms_for_variation not found"

    name_ids = {node.id for node in ast.walk(method) if isinstance(node, ast.Name)}
    method_attrs = {node.attr for node in ast.walk(method) if isinstance(node, ast.Attribute)}
    assert "build_channel_label" in name_ids or "build_channel_label" in method_attrs
