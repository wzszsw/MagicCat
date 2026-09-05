"""M133 回归：窗口级 UI 状态使用不可变快照和 typed reducer 管理。"""

from __future__ import annotations

import pytest


def test_reduce_state_returns_immutable_snapshots_and_normalizes_bounds():
    from magiccat.ui.state import (
        ObjectContextState,
        SetActiveTab,
        SetCurrentDomain,
        SetCurrentProfile,
        SetObjectContext,
        SetRunningQueries,
        UiState,
        reduce_state,
    )

    initial = UiState()
    context = ObjectContextState("profile-1", "catalog-1", "schema-1")
    current = reduce_state(initial, SetCurrentProfile("profile-1"))
    current = reduce_state(current, SetCurrentDomain("views"))
    current = reduce_state(current, SetObjectContext(context))
    current = reduce_state(current, SetActiveTab(-1))
    current = reduce_state(current, SetRunningQueries(-5))

    assert initial == UiState()
    assert current.current_profile_id == "profile-1"
    assert current.current_domain == "views"
    assert current.object_context == context
    assert current.active_tab == 0
    assert current.running_queries == 0
    assert current is not initial


def test_store_deduplicates_actions_and_emits_previous_and_current(qtbot):
    from magiccat.ui.state import SetCurrentDomain, UiStateStore

    store = UiStateStore()
    changes: list[tuple[object, object]] = []
    store.state_changed.connect(lambda previous, current: changes.append((previous, current)))

    unchanged = store.dispatch(SetCurrentDomain("tables"))
    assert unchanged == store.state
    assert changes == []

    updated = store.dispatch(SetCurrentDomain("views"))
    assert updated == store.state
    assert len(changes) == 1
    previous, current = changes[0]
    assert previous.current_domain == "tables"
    assert current.current_domain == "views"

    store.dispatch(SetCurrentDomain("views"))
    assert len(changes) == 1


def test_reducer_rejects_unknown_actions():
    from magiccat.ui.state import UiState, reduce_state

    with pytest.raises(TypeError, match="未知 UI action"):
        reduce_state(UiState(), object())  # type: ignore[arg-type]
