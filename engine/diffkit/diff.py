"""Line oriented comparison helpers for review previews.

Blocks are dictionaries with the following shape::

    {
        "type": "equal" | "add" | "delete" | "modify",
        "old_start": int,
        "old_lines": list[str],
        "new_start": int,
        "new_lines": list[str],
    }

Starts are line numbers in the corresponding side of the comparison.  An
insertion uses an empty old_lines list; a deletion uses an empty new_lines
list.
"""

from difflib import SequenceMatcher

_IGNORE_POLICIES = frozenset(
    {
        "ignore",
        "strip",
        "ignore_whitespace",
        "ignore_whitespace_changes",
        "ignore-all",
    }
)
_PRESERVE_POLICIES = frozenset({"preserve", "keep", "exact", "none", "off"})


def _policy_name(policy):
    if policy is None:
        return "preserve"
    if not isinstance(policy, str):
        raise ValueError("whitespace policy must be a string")
    return policy.strip().lower()


def split_lines(text):
    """Split text into lines, retaining the marker for a final newline."""
    if not isinstance(text, str):
        raise TypeError("text must be a string")
    lines = text.split("\n")
    if lines and lines[-1] == "":
        lines.pop()
    return lines


def _join_lines(lines):
    return "\n".join(lines)


def normalize_line(line, policy):
    """Normalize a line according to the requested whitespace policy."""
    if not isinstance(line, str):
        raise TypeError("line must be a string")
    name = _policy_name(policy)
    if name in _IGNORE_POLICIES:
        return line.rstrip()
    if name in _PRESERVE_POLICIES:
        return line
    raise ValueError("unknown whitespace policy: %s" % (policy,))


def _block(kind, old_start, old_lines, new_start, new_lines):
    return {
        "type": kind,
        "old_start": old_start,
        "old_lines": list(old_lines),
        "new_start": new_start,
        "new_lines": list(new_lines),
    }


def diff_blocks(a, b, policy="preserve"):
    """Return the changed blocks that turn a into b."""
    old_lines = split_lines(a)
    new_lines = split_lines(b)
    old_keys = [normalize_line(line, policy) for line in old_lines]
    new_keys = [normalize_line(line, policy) for line in new_lines]

    if not any(old_keys) and not any(new_keys):
        return []

    matcher = SequenceMatcher(None, old_keys, new_keys, autojunk=False)
    blocks = []
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        old_part = old_lines[i1:i2]
        new_part = new_lines[j1:j2]
        if tag == "equal":
            blocks.append(_block("equal", i1, old_part, j1, new_part))
        elif tag == "replace":
            blocks.append(_block("delete", i1, old_part, j1, []))
            blocks.append(_block("add", i1, [], j1, new_part))
        elif tag == "delete":
            blocks.append(_block("delete", i1, old_part, j1, []))
        elif tag == "insert":
            blocks.append(_block("add", i1, [], j1, new_part))
    return blocks


def apply_patch(original, blocks):
    """Apply a list of blocks to original and return the new text."""
    lines = split_lines(original)
    output = []
    cursor = 0
    for block in sorted(
        blocks,
        key=lambda item: (
            item["old_start"],
            0 if item.get("type") == "delete" else 1,
        ),
    ):
        start = block["old_start"] - 1
        if start < cursor:
            start = cursor
        if start > len(lines):
            start = len(lines)
        output.extend(lines[cursor:start])
        output.extend(block["new_lines"])
        end = block["old_start"] - 1 + len(block["old_lines"])
        if end > cursor:
            cursor = end
    output.extend(lines[cursor:])
    return _join_lines(output)


def reverse_patch(new_text, blocks):
    """Apply the inverse of blocks to new_text and return the original text."""
    lines = split_lines(new_text)
    output = []
    cursor = 0
    for block in sorted(blocks, key=lambda item: item["new_start"]):
        start = block["new_start"] - 1
        if start < cursor:
            start = cursor
        if start > len(lines):
            start = len(lines)
        if block.get("type") != "delete":
            continue
        output.extend(lines[cursor:start])
        output.extend(block["old_lines"])
        end = block["new_start"] - 1 + len(block["new_lines"])
        if end > cursor:
            cursor = end
    output.extend(lines[cursor:])
    return _join_lines(output)


def line_numbers(blocks):
    """Return the line ranges occupied by each block."""
    result = []
    for block in blocks:
        old_lines = block.get("old_lines", [])
        new_lines = block.get("new_lines", [])
        old_start = block.get("old_start")
        new_start = block.get("new_start")
        result.append(
            {
                "type": block.get("type"),
                "old_start": old_start,
                "old_end": old_start + len(old_lines) - 1 if old_lines else None,
                "new_start": new_start,
                "new_end": new_start + len(new_lines) - 1 if new_lines else None,
            }
        )
    return result


def validate_blocks(blocks, original):
    """Return a list of problems found while validating blocks."""
    issues = []
    for index, block in enumerate(blocks):
        old_lines = block.get("old_lines", [])
        new_lines = block.get("new_lines", [])
        if not old_lines and not new_lines:
            issues.append("block %d is empty" % index)
    return issues


def diff_batch(pairs, policy="preserve"):
    """Compare several text pairs and return results keyed by pair index."""
    result = {}
    shared = []
    for index, pair in enumerate(pairs):
        left, right = pair
        shared.extend(diff_blocks(left, right, policy))
        result[index] = shared
    return result