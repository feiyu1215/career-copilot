import importlib.util
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SCRIPT = REPO / "scripts" / "build_upskill_brief.py"
spec = importlib.util.spec_from_file_location("build_upskill_brief", SCRIPT)
bub = importlib.util.module_from_spec(spec)
sys.modules["build_upskill_brief"] = bub
spec.loader.exec_module(bub)

IDX = """# 资源索引

## hard技能

- [算法圣经](https://x.com/a) — 排序精练

## 软技能

- [表达训练](https://x.com/b)
"""


def test_load_and_map(tmp_path):
    p = tmp_path / "resource-index.md"
    p.write_text(IDX, encoding="utf-8")
    index = bub.load_resource_index(str(p))
    assert index["hard"]
    assert index["soft"]
    clusters = [{"dimension": "hard", "representative": "补算法", "count": 2, "weight": 3}]
    m = bub.map_clusters_to_resources(clusters, index)
    assert m["hard"]
    assert m["hard"][0][0] == "算法圣经"


def test_missing_file_returns_empty():
    index = bub.load_resource_index("/no/such.md")
    assert all(v == [] for v in index.values())
