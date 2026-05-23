"""User-controlled runtime state paths (not managed by deploy or env sync)."""

from __future__ import annotations

# Repo-root JSON written by ``external_layer/control.py`` and manual operator edits.
# ``nanoup`` must never reset this via ``git pull``, stash, or ``nanoenv_apply``.
CONTROL_JSON_FILENAME = "control.json"

# Files preserved across ``nanoup`` git operations (backup/restore + stash exclusion).
NANOUP_PRESERVE_RUNTIME_FILES: tuple[str, ...] = (CONTROL_JSON_FILENAME,)
