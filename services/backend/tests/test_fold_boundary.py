"""_fold_boundary 回合边界对齐(P1):折叠边界不许切断 assistant(tool_calls)↔tool 配对。"""

from types import SimpleNamespace

from agent_cloud_backend.turn.compaction import _fold_boundary


def _m(seq: int, role: str):
    return SimpleNamespace(seq=seq, role=role)


def _seq(*roles: str):
    return [_m(i, r) for i, r in enumerate(roles)]


def test_boundary_already_on_turn_start_keeps_plain_split():
    # [u a u a],keep 2 → 初步边界在 u(idx2)恰是回合开头 → 原样折 [u a]
    h = _seq("user", "assistant", "user", "assistant")
    fold, boundary = _fold_boundary(h, 2)
    assert [m.seq for m in fold] == [0, 1]
    assert boundary == 1


def test_boundary_mid_turn_swallows_partial_turn():
    # [u a t a u a],keep 3 → 初步边界落在 t(idx3=assistant?算清楚:idx = 6-3 = 3,
    # h[3]=assistant 属上一回合中段)→ 向后找 user 在 idx4 → 折 [0..3],保留段从 user 起
    h = _seq("user", "assistant", "tool", "assistant", "user", "assistant")
    fold, boundary = _fold_boundary(h, 3)
    assert [m.seq for m in fold] == [0, 1, 2, 3]
    assert boundary == 3


def test_orphan_tool_never_leads_kept_segment():
    # [u a t a t a u a],keep 5 → 初步边界 idx3(assistant 中段),硬切会让保留段以
    # 回合中段开头(后续含孤儿 tool)→ 对齐吞到 idx6 的 user
    h = _seq("user", "assistant", "tool", "assistant", "tool", "assistant", "user", "assistant")
    fold, _ = _fold_boundary(h, 5)
    kept_start = len(fold)
    assert h[kept_start].role == "user"  # 保留段必从回合开头(user)起


def test_no_user_ahead_falls_back_to_earlier_user():
    # [u a t t t],keep 1 → 初步边界 idx4,向后无 user → 向前找到 idx0 的 user →
    # 对齐后边界 0 = 无可折叠(唯一回合不能切)→ None
    h = _seq("user", "assistant", "tool", "tool", "tool")
    assert _fold_boundary(h, 1) is None


def test_two_turns_force_keep1_folds_first_turn_whole():
    # [u a t a u a],keep 1 → 初步边界 idx5(a),向后无 user → 向前最后一个 user 在 idx4
    # → 折 [0..3](第一回合整体),保留 [u a](最新回合完整)
    h = _seq("user", "assistant", "tool", "assistant", "user", "assistant")
    fold, boundary = _fold_boundary(h, 1)
    assert [m.seq for m in fold] == [0, 1, 2, 3]
    assert boundary == 3


def test_not_enough_to_fold_returns_none():
    assert _fold_boundary(_seq("user", "assistant"), 2) is None
    assert _fold_boundary(_seq("user"), 1) is None


def test_degenerate_no_user_at_all_splits_by_count():
    # 整段无 user(异常形态):退回按条数切,配对完整性交给 worker 层清洗兜底
    h = _seq("assistant", "tool", "assistant", "tool")
    fold, boundary = _fold_boundary(h, 2)
    assert [m.seq for m in fold] == [0, 1]
    assert boundary == 1
