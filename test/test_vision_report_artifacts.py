import json
from html.parser import HTMLParser
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
REPORT_DIR = ROOT / "docs" / "vision"


def test_report_metrics_and_links_are_consistent():
    metrics = json.loads((REPORT_DIR / "vision_100_metrics.json").read_text(encoding="utf-8"))
    report = (REPORT_DIR / "vision_dl_100_final_report.md").read_text(encoding="utf-8")
    html = (REPORT_DIR / "vision_dl_100_comparison.html").read_text(encoding="utf-8")
    assert metrics["scope"]["total_videos"] == 400
    assert metrics["qwen"]["qwen3"]["overall"]["model_json_valid"]["numerator"] == 394
    assert "394/400 (98.5%)" in report
    assert "394/400 (98.5%)" in html
    assert "350건 추가 분석" not in report
    assert "중단" not in report
    assert "350건" not in html

    class Parser(HTMLParser):
        def __init__(self):
            super().__init__()
            self.errors = []

        def error(self, message):
            self.errors.append(message)

    parser = Parser()
    parser.feed(html)
    assert parser.errors == []
    assert "https://" not in html


def test_notebook_code_cells_execute_from_repository_root(monkeypatch):
    notebook = json.loads(
        (REPORT_DIR / "vision_dl_100_analysis.ipynb").read_text(encoding="utf-8")
    )
    assert notebook["nbformat"] == 4
    monkeypatch.chdir(ROOT)
    namespace = {}
    for cell in notebook["cells"]:
        if cell["cell_type"] == "code":
            exec("".join(cell["source"]), namespace)
