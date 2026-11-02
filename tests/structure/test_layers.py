"""docs/ARCHITECTURE.md shows the layers the code really has (scripts/layers.py draws them)."""

import importlib.util
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "layers.py"
spec = importlib.util.spec_from_file_location("layers", SCRIPT)
layers = importlib.util.module_from_spec(spec)
spec.loader.exec_module(layers)


class LayerDiagramTest(unittest.TestCase):
    def test_diagram_matches_the_imports(self) -> None:
        drawn = layers.current_block(layers.DOC.read_text())
        self.assertEqual(drawn, layers.render(), "the layer diagram is stale: run python scripts/layers.py")

    def test_every_section_is_in_the_order(self) -> None:
        listed = {name for row in layers.layer_rows() for name in row}
        on_disk = {path.name for path in (layers.ROOT / "bot").iterdir() if (path / "__init__.py").exists()}
        self.assertEqual(on_disk | {"__main__"}, listed)
