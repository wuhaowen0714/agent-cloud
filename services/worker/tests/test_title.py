from agent_cloud_worker.title import clean_title


def test_clean_title_strips_paired_quotes():
    assert clean_title("「快排实现」") == "快排实现"
    assert clean_title('"Quick Sort"') == "Quick Sort"
    assert clean_title("“快排”") == "快排"


def test_clean_title_collapses_whitespace():
    assert clean_title("  快排\n实现   demo\t一下  ") == "快排 实现 demo 一下"


def test_clean_title_truncates_over_50_chars():
    out = clean_title("x" * 60)
    assert len(out) == 48 and out.endswith("…")


def test_clean_title_empty_input_stays_empty():
    assert clean_title("   \n  ") == ""
    assert clean_title("「」") == ""
