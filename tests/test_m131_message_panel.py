"""M131 回归：消息面板记录每条语句的结果和耗时。"""

from __future__ import annotations


def test_result_panel_logs_success_update_and_error(qtbot) -> None:
    from magiccat.ui.result_panel import ResultPanel

    panel = ResultPanel()
    qtbot.addWidget(panel)
    panel.show_results([
        {"kind": "query", "sql": "select 1", "columns": ["one"],
         "rows": [[1]], "time_ms": 46.0},
        {"kind": "update", "sql": "update books", "affected": 2,
         "time_ms": 12.0},
        {"kind": "error", "sql": "S", "message": "syntax error",
         "time_ms": 40.0},
    ])

    text = panel._log.toPlainText()
    assert "select 1\n> OK\n> 查询时间: 0.046s" in text
    assert "update books\n> OK\n> 影响行数: 2\n> 查询时间: 0.012s" in text
    assert "S\n> ERROR: syntax error\n> 查询时间: 0.040s" in text
