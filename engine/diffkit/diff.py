"""Line oriented comparison helpers for review previews.

Blocks are dictionaries with the following shape::

    {
        "type": "equal" | "add" | "delete" | "modify",
        "old_start": int,
        "old_lines": list[str],
        "new_start": int,
        "new_lines": list[str],
    }

Starts are 1-based line numbers in the corresponding side of the
comparison.  An insertion uses an empty old_lines list; a deletion uses an
empty new_lines list.

``split_lines`` normalizes CRLF/CR line endings to LF and retains the
trailing empty marker produced by a final newline.  That makes splitting
lossless (``"\\n".join(split_lines(text)) == text`` for LF text) and keeps
an empty file (``[""]``) distinguishable from a single blank line
(``["", ""]``).
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
    """Normalize line endings and split into lines.

    CRLF (and lone CR) endings are normalized to LF first.  The empty
    marker for a trailing newline is retained so that a final newline is
    significant and round trips are lossless.
    """
    if not isinstance(text, str):
        raise TypeError("text must be a string")
    normalized = text.replace("\r\n", "\n").replace("\r", "\n")
    return normalized.split("\n")


def _join_lines(lines):
    return "\n".join(lines)


def normalize_line(line, policy):
    """Normalize a line according to the requested whitespace policy."""
    if not isinstance(line, str):
        raise TypeError("line must be a string")
    name = _policy_name(policy)
    if name in _IGNORE_POLICIES:
        return line.strip()
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
    """Return only the changed blocks that turn a into b.

    Equal runs produce no block.  A replace opcode becomes a single
    ``modify`` block; insert and delete become ``add`` and ``delete``.
    Start numbers are 1-based on their respective side.
    """
    old_lines = split_lines(a)
    new_lines = split_lines(b)
    old_keys = [normalize_line(line, policy) for line in old_lines]
    new_keys = [normalize_line(line, policy) for line in new_lines]

    matcher = SequenceMatcher(None, old_keys, new_keys, autojunk=False)
    blocks = []
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            # Equal lines must never appear in the difference blocks.
            continue

        old_part = old_lines[i1:i2]
        new_part = new_lines[j1:j2]
        # difflib indices are 0-based; block line numbers are 1-based.
        old_start = i1 + 1
        new_start = j1 + 1

        if tag == "replace":
            blocks.append(
                _block("modify", old_start, old_part, new_start, new_part)
            )
        elif tag == "delete":
            blocks.append(
                _block("delete", old_start, old_part, new_start, [])
            )
        elif tag == "insert":
            blocks.append(
                _block("add", old_start, [], new_start, new_part)
            )
    return blocks


def _reconstruct(text, blocks, forward):
    """Replace spans on one side with the opposite side's content.

    ``forward=True`` replaces each block's old span with new_lines;
    ``forward=False`` replaces each block's new span with old_lines.
    """
    lines = split_lines(text)
    if forward:
        start_key = "old_start"
        span_key = "old_lines"
        replacement_key = "new_lines"
    else:
        start_key = "new_start"
        span_key = "new_lines"
        replacement_key = "old_lines"

    # Stable sort by start: blocks produced by diff_blocks already follow
    # opcode order, so blocks sharing a start keep insert-before-replace /
    # delete-before-replace ordering.  As a secondary rule, a zero-length
    # span block at a given position is emitted first.
    ordered = sorted(
        blocks,
        key=lambda block: (
            block[start_key],
            0 if not block.get(span_key) else 1,
        ),
    )

    output = []
    cursor = 0
    total = len(lines)

    for block in ordered:
        start = block[start_key] - 1
        span = block.get(span_key, [])
        replacement = block.get(replacement_key, [])

        start = max(0, min(start, total))
        end = start + len(span)
        if end > total:
            end = total
        if end < start:
            end = start

        output.extend(lines[cursor:start])
        output.extend(replacement)
        if end > cursor:
            cursor = end

    output.extend(lines[cursor:])
    return _join_lines(output)


def apply_patch(original, blocks):
    """Apply blocks forward to original and return the new text."""
    return _reconstruct(original, blocks, forward=True)


def reverse_patch(new_text, blocks):
    """Apply the inverse of blocks to new_text and return the original."""
    return _reconstruct(new_text, blocks, forward=False)


def line_numbers(blocks):
    """Return the 1-based line ranges occupied by each block."""
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
                "old_end": (
                    old_start + len(old_lines) - 1 if old_lines else None
                ),
                "new_start": new_start,
                "new_end": (
                    new_start + len(new_lines) - 1 if new_lines else None
                ),
            }
        )
    return result


def validate_blocks(blocks, original):
    """Return a list of problems found while validating blocks.

    Every block must be well formed and its old-side span must stay within
    the line range of ``original``; blocks carrying old content whose text
    does not match that span are also rejected as tampered.
    """
    issues = []
    original_lines = split_lines(original)
    total = len(original_lines)

    for index, block in enumerate(blocks):
        prefix = "block %d" % index
        if not isinstance(block, dict):
            issues.append("%s is not an object" % prefix)
            continue

        old_lines = block.get("old_lines", [])
        new_lines = block.get("new_lines", [])

        if not isinstance(old_lines, list) or not isinstance(new_lines, list):
            issues.append("%s has invalid line lists" % prefix)
            continue

        if not old_lines and not new_lines:
            issues.append("%s is empty" % prefix)
            continue

        old_start = block.get("old_start")
        if (
            not isinstance(old_start, int)
            or isinstance(old_start, bool)
            or old_start < 1
        ):
            issues.append("%s has invalid old_start" % prefix)
            continue

        start = old_start - 1
        end = start + len(old_lines)
        # A zero-length span may point one position past the last line
        # (an insertion at end of file), hence start <= total.
        if start > total or end > total:
            issues.append("%s is out of range" % prefix)
            continue

        if old_lines and old_lines != original_lines[start:end]:
            issues.append("%s does not match the original text" % prefix)

    return issues


def diff_batch(pairs, policy="preserve"):
    """Compare several text pairs; each index gets an independent result."""
    result = {}
    for index, pair in enumerate(pairs):
        left, right = pair
        result[index] = diff_blocks(left, right, policy)
    return result
