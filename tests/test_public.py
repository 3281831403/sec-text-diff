from engine.diffkit.diff import (
    diff_batch,
    diff_blocks,
    line_numbers,
    reverse_patch,
)


def test_identical_text_has_no_diff_blocks():
    text = "first\nsecond\nthird"
    assert diff_blocks(text, text, "preserve") == []


def test_single_line_change_creates_one_modify_block():
    blocks = diff_blocks(
        "first\nsecond\nthird",
        "first\nSECOND\nthird",
        "preserve",
    )
    assert len(blocks) == 1
    assert blocks[0]["type"] == "modify"
    assert blocks[0]["old_lines"] == ["second"]
    assert blocks[0]["new_lines"] == ["SECOND"]


def test_added_line_has_one_based_line_number():
    blocks = diff_blocks(
        "first\nsecond",
        "first\ninserted\nsecond",
        "preserve",
    )
    added = [item for item in line_numbers(blocks) if item["type"] == "add"]
    assert len(added) == 1
    assert added[0]["new_start"] == 2
    assert added[0]["new_end"] == 2


def test_reverse_patch_restores_original():
    original = "first\nsecond\nthird"
    modified = "first\ninserted\nsecond\nthird"
    blocks = diff_blocks(original, modified, "preserve")
    assert reverse_patch(modified, blocks) == original


def test_batch_keeps_pairs_independent():
    pairs = [("one", "two"), ("three", "four")]
    result = diff_batch(pairs, "preserve")
    assert result[0] == diff_blocks("one", "two", "preserve")
    assert result[1] == diff_blocks("three", "four", "preserve")