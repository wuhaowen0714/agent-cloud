from types import SimpleNamespace

from agent_cloud_backend.turn.compaction import _fold_boundary


def _m(seq):
    return SimpleNamespace(seq=seq)


def test_fold_boundary_keeps_recent_and_returns_boundary():
    hist = [_m(0), _m(1), _m(2), _m(3), _m(4)]  # keep_recent=2 → fold [0,1,2], boundary=2
    fold, boundary = _fold_boundary(hist, keep_recent=2)
    assert [m.seq for m in fold] == [0, 1, 2]
    assert boundary == 2


def test_fold_boundary_none_when_not_enough():
    assert _fold_boundary([_m(0), _m(1)], keep_recent=2) is None
    assert _fold_boundary([], keep_recent=2) is None
