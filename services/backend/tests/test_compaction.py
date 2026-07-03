from types import SimpleNamespace

from agent_cloud_backend.turn.compaction import _fold_boundary


def _m(seq, role="user"):
    return SimpleNamespace(seq=seq, role=role)


def test_fold_boundary_keeps_recent_and_returns_boundary():
    # P1 后边界按回合对齐:初步边界落在 assistant(seq3)→ 向后吞到 user(seq4)前,
    # 折叠 [0..3],保留段从回合开头(user)起。详尽用例见 test_fold_boundary.py。
    hist = [_m(0), _m(1, "assistant"), _m(2), _m(3, "assistant"), _m(4)]
    fold, boundary = _fold_boundary(hist, keep_recent=2)
    assert [m.seq for m in fold] == [0, 1, 2, 3]
    assert boundary == 3


def test_fold_boundary_none_when_not_enough():
    assert _fold_boundary([_m(0), _m(1)], keep_recent=2) is None
    assert _fold_boundary([], keep_recent=2) is None
