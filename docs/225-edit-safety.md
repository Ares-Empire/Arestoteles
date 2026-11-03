# 225: edit-safety audit

Worktree `codex/225-edit-safety`, 2026-11-03. Tests use the made-up fixture, temporary bare remotes and a second
“laptop” clone. No GitHub writes, server access, real notes, or changes to Aresync/iOS were made. Only the real
vault's `CLAUDE.md` was read. Its computer sync is specified as the Obsidian Git plugin.

**Round 2: staged version enforcement.** The original rollout order was incompatible in both directions: the
old server forbids the new version fields, and an enforcing server refuses the old client's missing versions.
`ARESTOTELES_REQUIRE_VERSIONS` now defaults off ([setting](../src/arestoteles/config.py#L34)). Supplied versions
are checked in either mode; missing structured-edit or linked-quick-note versions are accepted and logged once per
kind while off, and rejected with 428 while on ([edit check](../src/arestoteles/edits.py#L368),
[logging](../src/arestoteles/service.py#L269)). Compatibility mode deliberately retains the old unversioned
stale-edit risk; the full protection applies after enabling the switch.

Tests cover [each structured operation in both modes](../tests/test_edit_safety.py#L523),
[default/environment settings](../tests/test_version_rollout.py#L11),
[once-per-kind logging](../tests/test_version_rollout.py#L18),
[an actual stale version after a successful edit](../tests/test_version_rollout.py#L32), and unchanged requirements
for free-text/callout edits. Journal, recovery, locking, names and health behavior are unchanged. Deploy this server
with the setting off, ship brief 228's version-sending app and let the owner install it, then set it to 1 and restart.
See the [rollout procedure](../deploy/README.md#edit-safety-rollout-225). No deployment was performed here.

**Proven and fixed.** Regression tests reproduce these failure modes. Selected regressions were additionally rerun
against a temporary archive of the original HEAD (with its original test helper) to verify the old behavior.
The table names a primary test; parameterized and related tests cover the other cases described.

| What happened | Regression | Fix and location |
|---|---|---|
| Stale structured edits silently replaced a newer view, or used a position number after renumbering. | [test_an_unversioned_position_edit_cannot_overwrite_a_newer_view](../tests/test_edit_safety.py#L32) | With enforcement enabled, require the displayed note version (428 if missing); supplied stale versions always get 409. Threaded clients have one winner. [src/arestoteles/edits.py:343](../src/arestoteles/edits.py#L343) |
| A new discuss mark silently attached to a changed position because the two edits touched different files. | [test_a_discuss_mark_cannot_silently_follow_a_different_position](../tests/test_edit_safety.py#L403) | Persist read dependencies with commits; reject changed dependencies before replay, including after restart. [src/arestoteles/service.py:185](../src/arestoteles/service.py#L185) |
| A clean rebase combined two individually valid changes into duplicate note names and pushed a broken vault. | [test_a_clean_rebase_must_not_publish_a_broken_vault](../tests/test_edit_safety.py#L275) | Validate the combined tree against the remote baseline before pushing; reject/archive invalid combinations. [src/arestoteles/service.py:197](../src/arestoteles/service.py#L197) |
| Git skipped a pending patch that the laptop had applied and subsequently reverted, then reported the edit pushed. | [test_rebase_does_not_drop_a_patch_that_the_laptop_later_reverted](../tests/test_edit_safety.py#L359) | Reapply pending patches explicitly. [src/arestoteles/gitrepo.py:112](../src/arestoteles/gitrepo.py#L112) |
| A failing pre-rebase hook was treated as a content conflict and the current edit was removed. | [test_operational_rebase_failure_keeps_the_edit_pending](../tests/test_edit_safety.py#L43) | Distinguish operational failure from unmerged content; keep the commit pending. [src/arestoteles/gitrepo.py:112](../src/arestoteles/gitrepo.py#L112) |
| An abort failure could leave HEAD on the remote commit; the following HEAD~1 reset then moved the wrong history. | [test_abort_failure_never_resets_the_remote_commit](../tests/test_edit_safety.py#L299) | Verify abort/HEAD restoration; preserve the original under a durable ref and block unsafe operations. [src/arestoteles/gitrepo.py:132](../src/arestoteles/gitrepo.py#L132) |
| A push/fetch timeout escaped after commit, leaving a stale index and an error instead of reporting pending saved work. | [test_network_timeout_reports_a_committed_pending_edit](../tests/test_edit_safety.py#L54) | Treat timeouts as failed network attempts; answer 200 with pushed:false and retry. [src/arestoteles/gitrepo.py:99](../src/arestoteles/gitrepo.py#L99) |
| A short/failed write left partial notes; a failed commit restored files but left edited bytes staged. | [test_failure_halfway_through_a_multifile_edit_restores_every_file](../tests/test_edit_safety.py#L85) | Journal all originals first, replace files atomically, restore both bytes and index on failure. Also test failed_commit_restores_the_index_too. [src/arestoteles/transaction.py:78](../src/arestoteles/transaction.py#L78) |
| Process death before commit left uncommitted edits in the vault; death after commit hid pending state on restart. | [test_process_death_during_edit_recovers_on_restart](../tests/test_edit_safety.py#L135) | SIGKILL tests cover writing, before commit and after commit. Recover the transaction before indexing; remove only reserved temporary files. [src/arestoteles/transaction.py:96](../src/arestoteles/transaction.py#L96) |
| A source request could return the temporary text/version of an edit that was later rejected. | [test_source_never_reads_an_uncommitted_edit](../tests/test_edit_safety.py#L106) | Source reads share the edit lock. [src/arestoteles/service.py:79](../src/arestoteles/service.py#L79) |
| Two conflicts in one second overwrote the same recovery branch; failed branch uploads were never retried and health said everything was pushed. | [test_conflict_branches_are_unique_and_visible](../tests/test_edit_safety.py#L205) | Unique non-forced branches, upload retries, unhealthy status until reconciliation, and warnings naming branches. [src/arestoteles/service.py:221](../src/arestoteles/service.py#L221) |
| Restart, or a missing upstream ref, reported pushed:true despite local commits. | [test_restart_reports_pending_commits](../tests/test_edit_safety.py#L175) | Recompute pending state on startup; missing upstream is unsynced, not zero pending (gitrepo.py:85). [src/arestoteles/service.py:109](../src/arestoteles/service.py#L109) |
| Git lock files left every edit failing while health stayed green; a detached HEAD was guessed to mean main. | [test_a_stuck_clone_reports_unhealthy_and_refuses_edits](../tests/test_edit_safety.py#L191) | Refuse locks, unfinished operations, dirty checkouts and detached HEAD; report unhealthy. Locks are never deleted automatically. [src/arestoteles/gitrepo.py:52](../src/arestoteles/gitrepo.py#L52) |
| An ignored filename collision was overwritten, then deleted by rollback as a supposedly new quick note. | [test_ignored_quick_note_collision_cannot_overwrite_a_file](../tests/test_edit_safety.py#L224) | Refuse an existing creation target before journaling or writing it. [src/arestoteles/transaction.py:78](../src/arestoteles/transaction.py#L78) |
| A quick note whose composed name matched an existing decomposed filename overwrote the earlier note. | [test_quick_note_names_do_not_collide_across_unicode_normalizations](../tests/test_edit_safety.py#L619) | Compare canonical names (also ignoring case) before allocating the next numbered filename. [src/arestoteles/edits.py:299](../src/arestoteles/edits.py#L299) |
| NFC requests could not find NFD filenames; NFC Inbox links were unresolved and therefore not renumbered after a drop. | [test_nfc_inbox_links_follow_a_position_drop_in_an_nfd_note](../tests/test_edit_safety.py#L604) | Normalize comparisons without renaming files. The rebase dependency check also matches Git NFC paths to filesystem NFD paths. [src/arestoteles/inline.py:61](../src/arestoteles/inline.py#L61) |
| Decoding invalid UTF-8 with replacement characters silently corrupted original bytes on the next edit. | [test_invalid_utf8_is_not_silently_replaced_by_an_edit](../tests/test_edit_safety.py#L235) | Reject editing invalid UTF-8, keeping its bytes unchanged. [src/arestoteles/edits.py:78](../src/arestoteles/edits.py#L78) |
| A symlink edit wrote through to its target; duplicate note names silently selected the first path. | [test_symlink_note_is_not_replaced_or_written_through](../tests/test_edit_safety.py#L373) | Reject symlink edits; reject ambiguous notes in edits.py:78 (separate duplicate-name regression). [src/arestoteles/transaction.py:29](../src/arestoteles/transaction.py#L29) |
| Reword/change/drop discarded indented continuation lines without including them in history. | [test_structured_edits_do_not_discard_position_continuations](../tests/test_edit_safety.py#L424) | Reject these structured edits with 422 and direct the owner to the whole-note editor. [src/arestoteles/edits.py:112](../src/arestoteles/edits.py#L112) |
| A check that succeeded before the edit but crashed afterward was treated as a skipped check and the edit was approved. | [test_a_check_that_breaks_only_after_the_edit_does_not_approve_it](../tests/test_edit_safety.py#L440) | Roll back and return 503 when a previously working check cannot validate the edit. [src/arestoteles/service.py:281](../src/arestoteles/service.py#L281) |

Additional recovery regressions cover process death after Git finishes replaying but before the combined vault is
validated, a second competing push after rebase, multi-commit pending work across another restart/rebase, and
atomic replacement of an existing 244-byte filename. The atomic writer's initial temporary naming scheme was too
long for that filename; a fixed-length hash prefix avoids that regression.

**Checked and sound.** The existing whole-note and callout version checks reject stale content. Ordinary network
refusal already kept local commits and retried; that behavior remains. LF/CRLF handling preserves uniform Windows
line endings (`tests/test_notefile.py:43`). The new tests verify a large actual body is saved whole, an oversized
request receives 413 with no mutation, pathspec metacharacters leave other notes intact, moved/renamed notes do not
reappear at the old path, and a reloaded edit writes the new path. No-op behavior, check-error rollback, history,
Inbox renumbering, samples, authentication, search and existing API tests remain covered.

**Suspected or not proven.** These tests do not establish safety of Obsidian's own in-memory state, its Git plugin,
Windows scheduling, physical disk/controller failure, GitHub force-pushes, or two independent processes writing
the server clone. Deployment uses one writer. The tests kill processes and inject write/network/abort failures;
they are not power-loss testing. A lost HTTP response after a successful commit is still ambiguous to the client:
there is no request-id deduplication, so retrying a plain quick note can duplicate it. No edit loss from that path
was demonstrated. The documented policy still permits edits with warnings if Ruby/the check was already unavailable;
this cannot establish compliance with every vault rule.

**Aresync, read only.** `~/aresync/aresync.sh:384` and `windows/aresync.ps1:324` pull with rebase and abort/alert on
conflict. The script defaults to all repositories, and this Mac's selected config entries enable auto-commit/push
under `$HOME` with no REPOS override. There is a separate `~/opinions` directory (only directory metadata was
inspected). That does not establish that it is the active Documents/Weltbild checkout. The app's decision record
explicitly says the vault uses Obsidian Git and Aresync should stay out. Windows' documented Obsidian path is also
the default Aresync path, so Claude must verify that two sync writers do not share it. No Aresync commands or tests
were run, no configuration changed, and no machine-specific conflict was claimed as proven.

**Client and server handoff.** See [deployment steps](../deploy/README.md#edit-safety-rollout-225). The initially
installed iPhone client omitted structured-edit versions; brief 228 supplies them. Deploy the compatible server
first with `ARESTOTELES_REQUIRE_VERSIONS=0`, then ship the app and let the owner install it, then enable enforcement
and restart. Capture versions when drafts open and preserve them with queued `about` notes. Fetching a new version
only at send time defeats the protection. Keep failed drafts/queued notes on the phone. No iPhone build was changed
or tested in this repository.

Before the server rollout, stop the service, snapshot the whole clone including `.git`, inspect pending/recovery
refs and dirty/unfinished Git state, then deploy/restart and verify health plus GitHub publication. Keep dependency
records, journals and recovery refs in backups. Resolve archived work manually and remove only resolved local
recovery branches. Do not blindly reset the clone or delete locks. No deployment was performed here.

**Validation.** Run with `GIT_CONFIG_GLOBAL=/dev/null`. The workspace's pre-existing `.venv` symlink was broken;
a separate `/tmp/arestoteles-225-venv` was used and the symlink left untouched. The full permitted test command is:

```sh
GIT_CONFIG_GLOBAL=/dev/null /tmp/arestoteles-225-venv/bin/python -m pytest -q --ignore=tests/test_real_vault.py
```

The real-vault tests are excluded because they read/copy notes, contrary to this task's explicit boundary. Their
request helper was updated for the version requirement, but they were not executed. Model tests skip without model
files. The baseline had one unrelated failing web configuration assertion: it expected proxy `172.18.0.1` despite
the compose file's already-recorded verified `172.19.0.1`. The assertion now matches the existing config; production
web settings were not changed.

Round 1 results: the final full run passed **320 tests**, with **2 model tests skipped**. Four focused checks passed after
that run: the two Unicode regressions, the ordinary add/add conflict abort, and the already-covered failed abort.
That covers **323 distinct passing cases**, including **53 new edit-safety cases**. `git diff --check` passes.
The separate original-HEAD replay failed all 13 selected regression cases as expected; the Unicode filename
collision replay also failed, showing the old note's contents actually replaced by the new quick note.

Round 2 results: rollout tests were written first and failed against the enforcing-only implementation (including
an old-style request receiving 428 instead of 200). After the switch, the full permitted suite passed **345 tests**,
with **2 model tests skipped**, in 205 seconds. This includes every structured edit in both modes, an actual stale
version after a newer edit, once-per-kind logging, environment parsing, and unchanged free-text/callout requirements.
The same temporary environment and real-vault exclusion above apply. `git diff --check` passes.
