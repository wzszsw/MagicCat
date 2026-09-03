"""M16 测试：超长单元格截断/完整值保留 + 文件日志。"""

from __future__ import annotations

import logging

from PySide6.QtCore import QModelIndex, Qt


def test_long_cell_truncation_and_full_copy(qtbot):
    from magiccat.ui.grid import DISPLAY_LIMIT, ResultTableModel, ResultView

    long_text = "长" * 5000
    model = ResultTableModel(["k", "v"], [["1", long_text]])
    view = ResultView()
    qtbot.addWidget(view)
    view.setModel(model)

    idx_v = model.index(0, 1, QModelIndex())
    shown = model.data(idx_v)
    assert shown.endswith("…") and len(shown) <= DISPLAY_LIMIT
    assert model.data(idx_v, role=Qt.ToolTipRole) == long_text  # ToolTipRole = 完整值
    assert model.data(model.index(0, 0, QModelIndex())) == "1"  # 短值不受影响

    # 复制仍取完整原文（原始行路径）
    text = view.copy_selection(include_header=True)
    assert long_text in text and "…" not in text.splitlines()[-1]


def test_logging_file(tmp_path):
    from magiccat.utils.logging_setup import configure_logging

    configure_logging(tmp_path)
    configure_logging(tmp_path)  # 幂等
    logging.getLogger("magiccat.test").info("hello log")
    log_file = tmp_path / "logs" / "magiccat.log"
    assert log_file.exists()
    assert "hello log" in log_file.read_text(encoding="utf-8")
