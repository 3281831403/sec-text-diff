"""Line oriented text diff utilities."""

from .diff import (
    apply_patch,
    diff_batch,
    diff_blocks,
    line_numbers,
    normalize_line,
    reverse_patch,
    split_lines,
    validate_blocks,
)

__all__ = [
    "split_lines",
    "normalize_line",
    "diff_blocks",
    "apply_patch",
    "reverse_patch",
    "line_numbers",
    "validate_blocks",
    "diff_batch",
]