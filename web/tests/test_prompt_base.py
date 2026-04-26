from app import build_prompt_base


def test_drop_builtin_excludes_builtin_from_base():
    parts, base = build_prompt_base(
        "builtin tags",
        "direct tags",
        drop_builtin=True,
    )

    assert parts == ["direct tags"]
    assert base == "direct tags"


def test_keep_builtin_preserves_order():
    parts, base = build_prompt_base(
        "builtin tags",
        "direct tags",
        drop_builtin=False,
    )

    assert parts == ["builtin tags", "direct tags"]
    assert base == "builtin tags, direct tags"
