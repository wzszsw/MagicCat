"""UI 状态容器：不可变状态 + typed action/reducer。

该模块只管理跨组件的导航状态。查询标签自己的连接、Catalog、Schema 和编辑内容
仍由 ``QueryWorkspace`` 持有，避免全局状态覆盖独立标签。
"""

from __future__ import annotations

from dataclasses import dataclass, replace

from PySide6.QtCore import QObject, Signal


@dataclass(frozen=True, slots=True)
class ObjectContextState:
    """左侧对象树最近激活的上下文。"""

    profile_id: str
    database: str
    schema: str


@dataclass(frozen=True, slots=True)
class UiState:
    """跨页面共享的只读 UI 状态快照。"""

    current_profile_id: str | None = None
    current_domain: str = "tables"
    object_context: ObjectContextState | None = None
    active_tab: int = 0
    running_queries: int = 0


@dataclass(frozen=True, slots=True)
class SetCurrentProfile:
    profile_id: str | None


@dataclass(frozen=True, slots=True)
class SetCurrentDomain:
    domain: str


@dataclass(frozen=True, slots=True)
class SetObjectContext:
    context: ObjectContextState | None


@dataclass(frozen=True, slots=True)
class SetActiveTab:
    index: int


@dataclass(frozen=True, slots=True)
class SetRunningQueries:
    count: int


type UiAction = (
    SetCurrentProfile
    | SetCurrentDomain
    | SetObjectContext
    | SetActiveTab
    | SetRunningQueries
)


def reduce_state(state: UiState, action: UiAction) -> UiState:
    """纯 reducer：不修改旧快照，只返回新状态。"""
    if isinstance(action, SetCurrentProfile):
        return replace(state, current_profile_id=action.profile_id)
    if isinstance(action, SetCurrentDomain):
        return replace(state, current_domain=action.domain)
    if isinstance(action, SetObjectContext):
        return replace(state, object_context=action.context)
    if isinstance(action, SetActiveTab):
        return replace(state, active_tab=max(0, action.index))
    if isinstance(action, SetRunningQueries):
        return replace(state, running_queries=max(0, action.count))
    raise TypeError(f"未知 UI action: {type(action).__name__}")


class UiStateStore(QObject):
    """线程安全边界外的主线程 UI 状态存储；action 分发在 Qt 主线程执行。"""

    state_changed = Signal(object, object)  # previous, current

    def __init__(self, initial: UiState | None = None,
                 parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._state = initial or UiState()

    @property
    def state(self) -> UiState:
        return self._state

    def dispatch(self, action: UiAction) -> UiState:
        previous = self._state
        current = reduce_state(previous, action)
        if current == previous:
            return current
        self._state = current
        self.state_changed.emit(previous, current)
        return current
