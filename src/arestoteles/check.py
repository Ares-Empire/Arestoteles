"""The vault's own check (`ruby -E UTF-8:UTF-8 .tools/check.rb`, run inside the clone) and its output.

The script prints its warnings as "  ! …" lines under "Warnings:" and its errors as "  x …" lines under "ERRORS:",
and exits 1 when there are errors (see the script in the vault).
"""

from __future__ import annotations

import logging
import shutil
import subprocess
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

log = logging.getLogger("arestoteles")

SCRIPT = ".tools/check.rb"


@dataclass(frozen=True)
class CheckResult:
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    skipped: str | None = None    # why it did not run: a key of texts.TEXTS ("check_no_ruby", …)

    def new_since(self, before: CheckResult | None) -> CheckResult:
        """Only what `before` did not have (an edit answers for its own effects, not for the vault's old state)."""
        if before is None or before.skipped:
            return self
        return CheckResult(_minus(self.errors, before.errors), _minus(self.warnings, before.warnings), self.skipped)


def _minus(after: list[str], before: list[str]) -> list[str]:
    left = Counter(before)
    out = []
    for line in after:
        if left[line]:
            left[line] -= 1
        else:
            out.append(line)
    return out


def parse(output: str) -> tuple[list[str], list[str]]:
    errors, warnings, current = [], [], None
    for line in output.splitlines():
        if line.startswith("Warnings:"):
            current = warnings
        elif line.startswith(("ERRORS:", "Errors:")):
            current = errors
        elif current is warnings and line.startswith("  ! "):
            warnings.append(line[4:].strip())
        elif current is errors and line.startswith("  x "):
            errors.append(line[4:].strip())
        elif line and not line.startswith(" "):
            current = None
    return errors, warnings


def run(root: Path, ruby: str = "ruby", timeout: float = 60.0) -> CheckResult:
    if shutil.which(ruby) is None:
        return CheckResult(skipped="check_no_ruby")
    if not (root / SCRIPT).is_file():
        return CheckResult(skipped="check_missing")
    try:
        done = subprocess.run([ruby, "-E", "UTF-8:UTF-8", SCRIPT], cwd=root, capture_output=True, text=True,
                              encoding="utf-8", errors="replace", timeout=timeout)
    except (OSError, subprocess.TimeoutExpired) as e:
        log.warning("vault check did not run: %s", e)
        return CheckResult(skipped="check_broken")
    errors, warnings = parse(done.stdout)
    if done.returncode not in (0, 1) or (done.returncode == 1 and not errors):
        log.warning("vault check stopped (exit %d): %s", done.returncode, done.stderr.strip()[:300])
        return CheckResult(skipped="check_broken")
    return CheckResult(errors, warnings)
