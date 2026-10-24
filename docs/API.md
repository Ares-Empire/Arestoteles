# Arestoteles API (version 1): Patrik's Weltbild vault for the iPhone app

Decided 2026-10-24 ([ares-empire/docs/ARESTOTELES-APP.md](https://github.com/Ares-Empire/ares-empire/blob/main/docs/ARESTOTELES-APP.md)).
The server reads the vault and does every rule of it; the app only displays and sends edits.

**Base URL:** `https://www.ares-empire.de/api/arestoteles` (Caddy routes `/api/arestoteles/*` to `127.0.0.1:8099`,
keeping the path). JSON, UTF-8. Dates `YYYY-MM-DD` (Berlin), timestamps ISO 8601 with `Z`.

**Auth:** `Authorization: Bearer <Empire token>`, checked like every Empire service
([ACCOUNTS.md → How a service checks a login](https://github.com/Ares-Empire/ares-empire/blob/main/docs/ACCOUNTS.md#how-a-service-checks-a-login)):
`auth-refresh` answers 200 and `services` contains `arestoteles`; cached 60 s per token. Errors are
`{"error": "<one sentence>"}` in the request's language (`Accept-Language`, ares-empire/docs/LANGUAGES.md):
`401` token rejected · `403` no `arestoteles` service · `503` account server unreachable · `404` unknown note or
position · `409` changed elsewhere (body adds `"current"`, see Edits) · `422` an edit that cannot apply.
Vault content (titles, text, glossary) is never translated.

**The vault** is the git repo `carlsenares/opinions` (Obsidian; its rules are its own `CLAUDE.md`). The server keeps a
clone at `/var/lib/arestoteles/vault` (deploy key, read + write), pulls every 60 s and rebuilds the index when the commit
changed. Edits are written there, checked with the vault's own check (`ruby -E UTF-8:UTF-8 .tools/check.rb`), committed
as `Patrik Breeck (Arestoteles app) <287037715+carlsenares@users.noreply.github.com>` and pushed.

## Routes

| Route | Answer |
|---|---|
| `GET /vault` | `Vault`, the whole index. `ETag` = the vault commit plus the index's shape version (`"8db2491-2"`, CONTRACT ADDITION: a server update that adds fields reaches phones without a vault change); `If-None-Match` → `304`. |
| `GET /notes/{id}/source` | `{id, version, markdown}`: the note's body as Markdown (without frontmatter), for the free editor. |
| `POST /edits` `Edit` | `EditResult`. |
| `GET /search?q=<query>&limit=<n>` | `SearchAnswer`: the passages that answer a query, best first, by their words and their meaning (see Search). |
| `GET /health` | **no login** (for Aresus): `{"ok": bool, "commit": string, "pulled": "…Z", "pushed": bool, "notes": n}`; `ok` is false when the last pull or push failed for more than 10 minutes. |

`{id}` is URL-encoded (note ids contain spaces and apostrophes).

CONTRACT ADDITION (server, 2026-10-24): `pulled` is `null` until the first successful pull, and `pushed` is false
while app commits wait for GitHub. Before the first index is built (no clone yet), the routes with login answer
`503 {"error"}` ("still loading"); `/health` answers `ok: false`.

## Types

```ts
interface Vault {
  version: 1;
  commit: string;                 // the vault's git commit the index was built from (short hash)
  built: string;                  // when the server built it
  notes: Note[];                  // every note except Templates/ and CLAUDE.md, sorted by id
  positions: PositionGroup[];     // Positions.md: "Across topics" first, then each topic in that page's order
                                  // (CONTRACT ADDITION: topics with positions the page does not embed yet follow,
                                  // sorted by id, so no position is hidden)
  glossary: Term[];               // Glossary.md, sorted by English
  home: { learn_next: string[] }; // Home.md "To learn about next": inline Markdown items, links resolved
}

type NoteType = "topic" | "mechanism" | "event" | "actor" | "question" | "session" | "inbox" | "home" | "positions" | "glossary";

interface Note {
  id: string;                     // the file name without .md: unique in the vault (the check enforces it)
  path: string;                   // "Topics/Colonialism/Colonialism.md"
  type: NoteType;
  title: string;                  // the first "# " heading, else the id
  summary: string | null;         // the "> [!summary]" box, inline Markdown (see Text)
  confidence: "solid" | "my-read" | "shaky" | null;
  created: string | null;         // frontmatter `created` (CONTRACT ADDITION: else `date`, as sessions have)
  updated: string | null;
  tags: string[];
  topic: string | null;           // the topic overview this note belongs to: itself for an overview, the overview for
                                  // a section page (Topics/<Topic>/…), null outside Topics/
  part_of: { note: string; section: number } | null;   // "*Part of [[X]], section N.*" on section pages
  event: { from: number | null; to: number | null; where: string[] } | null;   // events only (years, negative = BCE)
  led_to: string[];               // note ids (resolved [[links]] of the frontmatter list)
  links: string[];                // note ids this note links to, in order of first appearance, without duplicates
  backlinks: string[];            // note ids that link here, sorted by id
  positions: string[];            // ids of the positions written on this note (its "## My position"), in order
  callouts: Callout[];            // the note's "> [!claude]" and "> [!shaky]" callouts, in order (summary boxes excluded)
  blocks: Block[];                // the body for display (frontmatter, the title and the summary box left out)
  brief: Brief | null;            // topic overviews only
  inbox: Inbox | null;            // CONTRACT ADDITION (2026-10-24, lookup): Inbox notes only
  version: string;                // git blob hash of the file: edits of the text name it
}

// CONTRACT ADDITION (2026-10-24, lookup): an Inbox note's state, from its frontmatter.
interface Inbox {
  status: string;                 // `status`: "new" until processed, then "processed" ("new" when missing)
  kind: "note" | "discuss";       // "discuss": a "discuss later" mark (`kind: discuss`), else a note
  about: string | null;           // `about: "[[Note]]"` (or "[[Note#My position]]") resolved to a note id
  position: number | null;        // `position: N`: the position of `about` it is about ("<about>#<N>")
}                                 // The `about` link counts in `links` and `backlinks`, as in Obsidian.

type Block = (
  | { kind: "heading"; level: 2 | 3 | 4; text: Text; anchor: string }   // anchor: the heading text, as Obsidian links it
  | { kind: "paragraph"; text: Text }
  | { kind: "list"; ordered: boolean; items: { text: Text; depth: number; lines: Lines }[] }   // depth 0 = top level
  | { kind: "positions"; ids: string[] }          // the "## My position" list: the app shows position cards here
  | { kind: "callout"; style: "claude" | "shaky" | "note"; title: Text | null; text: Text; index: number }
                                                  // index: position in Note.callouts; other callout types → "note"
  | { kind: "quote"; text: Text }
  | { kind: "embed"; note: string; anchor: string | null }   // ![[Note#Heading]]: the app shows that part
  | { kind: "table"; header: Text[]; rows: Text[][] }
  | { kind: "section_link"; note: string }        // a "→ [[Section page]]" line on its own
  | { kind: "rule" }
) & { lines: Lines };

// CONTRACT ADDITION (2026-10-24, lookup): where a block (or list item) sits in the note's source, so the app can
// edit exactly that paragraph or list item. [start, end): 0-based line numbers, end exclusive, in the `markdown` of
// GET /notes/{id}/source split at "\n" (that body still has the title line and the summary box that `blocks` leave
// out). The lines are the raw Markdown (list markers, "> " and indentation included); the range has no blank lines at
// its ends. A list item runs from its marker line to the next item (a nested
// item has its own range) or the end of the list. Blocks from one line share it (a "→ [[A]], [[B]]" line gives two
// section links). null only for blocks the server makes up (none today) and for a note whose text has a lone
// carriage return (where line counts would differ).
// To edit a block: fetch the source, check its `version` is the note's (else reload the vault: the lines belong to
// that version), replace lines[start..<end] with the new text's lines, join with "\n", send `edit_note` with that
// version (a file changed since answers 409 as always).
type Lines = [number, number] | null;

// Text: inline Markdown the app renders with AttributedString(markdown:): **bold**, *italic*, `code`, and links.
// [[Note]], [[Note|alias]] and [[Note#Heading]] become [shown text](arestoteles://note/<id>#<anchor>) (id and anchor
// percent-encoded); a link to a note that does not exist stays plain text. Web links stay as they are.
// CONTRACT ADDITION (server): the shown text is what Obsidian shows: the alias, else "Note > Heading", else the note
// name, with Markdown characters escaped. A line break inside a paragraph stays "\n" (Obsidian shows it). A callout's
// or quote's text keeps its paragraphs apart with a blank line and its list items as "• " lines. Block `callout` of
// style "note" (not in Note.callouts) has index -1.

interface Callout { index: number; style: "claude" | "shaky"; title: string | null; text: Text }

interface Position {
  id: string;                     // "<note id>#<number>": "Colonialism#2", "Positions#3" (across topics)
  note: string;                   // the note it is written on (a topic overview, or "Positions")
  number: number;                 // its number in that list (1, 2, …)
  text: Text;                     // the sentence without its bold markers, "(draft)" and the → links
  title: Text;                    // CONTRACT ADDITION (2026-10-24, short cards): the bold part alone, without a trailing
                                  // ",", ";" or ":"; the whole text when nothing or everything is bold
  draft: boolean;                 // marked "(draft)": worded by Claude, not yet confirmed by Patrik
  evidence: string[];             // note ids from the "→ [[…]], [[…]]" part
  history: { date: string; text: Text; why: Text | null }[];   // from the note's "## How my view changed", newest first
}

interface PositionGroup { title: string; note: string; positions: Position[] }   // positions in full, not ids

interface Term { english: string; german: string; note: string | null }   // the "Where" link, resolved

interface Brief {                 // a topic before a discussion, built from the vault's structure (no AI)
  positions: string[];            // position ids
  sections: { title: string; summary: Text; note: string | null }[];  // the overview's numbered sections
                                  // (CONTRACT ADDITION: summary = the section's first paragraph, title without "N.")
  counterpoints: { note: string; title: string | null; text: Text }[]; // [!claude] callouts of the topic's notes
  shaky: { note: string; text: Text }[];       // [!shaky] callouts of the topic's notes
  terms: Term[];                  // glossary terms whose "Where" note belongs to this topic
  questions: string[];            // question notes linked from the topic's notes
}
```

## Edits

```ts
type Edit =
  | { op: "confirm_position"; position: string }                 // removes "(draft)"
  | { op: "reword_position"; position: string; text: string }    // same view, better words: no history
  | { op: "change_position"; position: string; text: string; why: string }
        // a changed view: the old sentence goes to "## How my view changed" (dated, with why), the new one replaces it
  | { op: "drop_position"; position: string; why: string }       // no longer held: into the history, removed from the list
  | { op: "add_position"; note: string; text: string; evidence: string[] }
        // a topic overview's "## My position" (created after the summary box if missing), or "Positions" (across topics)
  | { op: "set_confidence"; note: string; confidence: "solid" | "my-read" | "shaky" }
  | { op: "adopt_callout"; note: string; callout: number; version: string }
        // Patrik agrees: the callout's text becomes a normal paragraph in its place (vault voice rule 2)
  | { op: "dismiss_callout"; note: string; callout: number; version: string }
  | { op: "edit_note"; note: string; version: string; markdown: string }   // the free editor: the whole body
  | { op: "quick_note"; text: string; about?: string | null; kind?: "note" | "discuss" }
        // a new Inbox note, status new, verbatim
        // CONTRACT ADDITION (2026-10-24, lookup): `about` (optional) is a note id or a position id "<note>#<n>";
        // `kind` (optional, default "note"): "discuss" is a "discuss later" mark, whose `text` may be empty when it
        // has an `about`
  | { op: "set_inbox_status"; note: string; status: "new" | "processed" };
        // CONTRACT ADDITION (2026-10-24, lookup): sets an Inbox note's `status` (the app ticks off a discussed mark)

interface EditResult {
  vault: Vault;                   // rebuilt after the edit
  changed: string[];              // note ids the edit touched (a quick note: the new Inbox note)
  pushed: boolean;                // false: committed, push waits for GitHub (the sync loop retries)
  warnings: string[];             // the vault check's warnings after the edit (errors undo the edit: 422)
}
```

Rules every edit follows (they are the vault's own, `CLAUDE.md` there):
- Positions are Patrik's words: text is used as given, trimmed, one sentence; the server keeps the bold, the numbering,
  the `→` links and Positions.md's embeds intact, and renumbers after a drop.
- `change_position` / `drop_position` write `- **YYYY-MM-DD:** I thought: <old text>. What changed it: <why>` under
  `## How my view changed` on the same note (created before `## Sources`, else at the end), newest first. Beliefs change;
  they are not overwritten.
  CONTRACT ADDITION (needed for `Position.history`): `change_position` writes the position's number into the date,
  `- **2026-10-24, position 2:** I thought: …`, and `Position.history` is the entries naming its number. A
  `drop_position` entry has no number (the position is gone); after a drop, entries of the dropped position lose their
  number and those of later positions are renumbered with the list. An entry without a number belongs to no position.
- CONTRACT ADDITION: `reword_position` and `change_position` remove "(draft)": the new words are Patrik's (a draft
  is a position worded by Claude). `add_position` on a topic overview without `## My position` also adds
  `![[<Topic>#My position]]` under `## By topic` on Positions.md (`changed` then lists both notes).
- Every edit sets the note's `updated` to today; `quick_note` creates `Inbox/YYYY-MM-DD HHMM <first words>.md` with
  `type: inbox`, `status: new`, `created`, the text verbatim (it is raw input, never rewritten).
  CONTRACT ADDITION (2026-10-24, lookup): with `kind: "discuss"` the frontmatter adds `kind: discuss`; with `about`
  a note, `about: "[[<note>]]"`; with `about` a position, `about: "[[<note>#My position]]"` (`#Across topics` for
  Positions.md) and `position: <n>`. A discuss mark without text is named `… HHMM discuss <note title>.md` and has an
  empty body. `422` when the text is empty (for a discuss mark: when it has no `about` either), `404` for an unknown
  note or a note without positions, `409` (with `current`) for a position that no longer exists. The commit message is
  `App: discuss later (<name>)` for a mark. `set_inbox_status` answers `422` for a note that is not an Inbox note;
  the same status again changes nothing.
- CONTRACT ADDITION (2026-10-24, lookup): `drop_position` also updates the Inbox notes about that note's positions,
  as it does the history entries: a note about the dropped position loses its `position` (it stays about the note),
  notes about later positions move up by one (each gets `updated`); `changed` then lists them after the note. The
  Inbox note's text is never touched.
- **Versions:** an edit naming `version` fails with `409 {"error", "current": Note}` when the file changed since. Position
  edits find their position by id; when it no longer exists the answer is `409` too.
- A vault check *error* after an edit undoes it (`422`, the errors in `error`); *warnings* are returned, the edit stays.
  CONTRACT ADDITION: both count only what the edit added, compared with the check before it (a warning the vault
  already had is not returned; an old error elsewhere does not block edits). Without Ruby (or without the script) the
  check is skipped and `warnings` says so in the request's language.
- CONTRACT ADDITION: an edit that changes nothing (confirming a confirmed position, the same confidence) answers 200
  with `changed: []` and makes no commit. An unknown callout index answers `404`.
- One commit per edit, message `App: <what> (<note>)`, e.g. `App: confirm position 2 (Colonialism)`.
- Conflicts with a push from elsewhere: pull with rebase and push again; a real conflict undoes the edit and answers `409`.
  CONTRACT ADDITION: when the sync loop cannot replay an app commit that was still waiting for GitHub (a real
  conflict with an edit from elsewhere), the commit is kept on the branch `arestoteles-app/conflict-<time>` (pushed
  when GitHub is reachable) and the clone follows GitHub; nothing is lost, nothing is merged by guesswork.

## Search

`GET /search?q=<query>&limit=<n>` (contract of 2026-10-24, `empire-ios/docs/build-2026-10-24/briefs/E-search-contract.md`):
passages of the vault that answer a query, best first, found by their words and by their meaning: a German question
finds an English passage, a question in other words finds the passage. No AI writes text: every result is a passage
of the vault as it stands. Login as every route; `503` before the first index.

- **Query:** `q` 1–200 characters after trimming, `limit` 1–30 (default 12); anything else answers `400 {"error"}` in
  the request's language.

```ts
interface SearchAnswer {
  commit: string;                 // the vault commit the results come from (the ETag of /vault before the "-")
  meaning: boolean;               // false while the meaning model is not ready: the results are then word matches only
  results: SearchResult[];        // best first, at most `limit`
}

interface SearchResult {
  note: string;                   // the note's id (as in /vault)
  block: number;                  // index in that note's `blocks`
  item: number | null;            // for a list: the item's index in the list; else null
  position: string | null;        // for a position: its id (`note`/`block` are the note and the positions block it
                                  // stands in); else null
  heading: string | null;         // the heading the passage stands under, plain text
  text: Text;                     // the whole passage, inline Markdown as in /vault
  sentence: string;               // the passage's one sentence that answers best, plain text (the whole passage if it
                                  // is one sentence)
  match: "words" | "meaning" | "both";   // "words": holds words of the query; "meaning": found by its meaning only
}
```

- **Passages** are every paragraph, list item, quote, callout and position of the notes people read: not the `home`,
  `positions` and `glossary` index pages (the app's `VaultSearch` skips the same types), but the positions written on
  Positions.md are passages too (`note` "Positions", the "Across topics" block). A callout's `text` is its title in
  bold before its text, as the app's `Lookup` shows it (its `sentence` comes from the text). A section page's
  "*Part of [[X]], section N.*" line is no passage. CONTRACT ADDITION: a **table** is one passage too (`item` null):
  `text` is its rows as lines, header first, cells joined by " · " (`City · First press`, `Mainz · 1450`), and
  `sentence` is the row that answers (so a figure in a table is found).
- **Words:** the query's words in the passage, and more weakly in the heading above it and its note's title, with the
  app's folding (case and accents: "Handelsstadte" finds "Handelsstädte"), word beginnings ("Druck" finds
  "Druckorte"), other endings of the same word ("printing" finds "printers"), and weakly inside longer words; numbers
  only as they are. Small words ("the", "der", "wie") count only when the query has nothing else. Scored with BM25.
- **Meaning:** a multilingual sentence-embedding model on the server's CPU (EmbeddingGemma-300m, 4-bit, through ONNX
  Runtime; chosen in `scripts/search_eval.py`, numbers in `deploy/README.md`). A passage counts with the closer of
  itself and its closest sentence (a table: its closest row), so one fact in a long paragraph is found too. The model
  reads each passage with where it stands (the note's title and the heading).
- **Ranking:** half how close the passage is in meaning (scaled from the model's floor to the query's closest
  passage), half how much of the query's words it holds (BM25 over the query's total), plus a bonus when it holds every
  word of the query (one at least in its own text), so those rank higher. `match` is "words" when it holds words of the
  query (the app can mark them in `sentence`), "meaning" when it is among the `limit` passages closest in meaning and
  holds none of the words, "both" for both. `sentence` is the passage's sentence holding the most of the query's words,
  then the closest in meaning. A query that nothing in the vault is close to and no passage holds answers no results.
- **`meaning: false`** while the model is not ready: just after a start (the model loads and, the first time, embeds
  every passage, which takes about a minute), and CONTRACT ADDITION: for the few seconds after a pull or an edit
  changed passages (only the changed ones are embedded again; the others come from the cache), and always when the
  server has no model files (`deploy/README.md` → Meaning search). The word matches answer at once in every case.

## Language

Requests send `Accept-Language` (ares-empire/docs/LANGUAGES.md): German when the highest-weighted `de`/`en` tag is
German, otherwise English. Every answer sets `Content-Language: de|en` (and `Vary: Accept-Language`). The language
applies only to the server's own sentences: every `error`, and the warnings the server writes itself (check skipped).
The vault check's own warning lines, all vault content (titles, text, glossary), ids, codes and dates never change.

## Samples

`docs/samples/vault.json` (a small made-up vault, never Patrik's notes), `docs/samples/note-source.json`,
`docs/samples/edit-result.json`, `docs/samples/search.json`: used by the app's tests and sample mode. Keep them valid
when the contract changes. The made-up vault is `tests/fixtures/vault/`: it builds exactly `vault.json` (with the
sample's commit, build time and versions; `tests/test_samples.py`). `search.json` is the server's real answer on that
vault for "Wie viele Bücher wurden bis 1500 gedruckt?" (limit 5) with the real model: after a change to the search,
`ARESTOTELES_MODELS=models .venv/bin/python scripts/make_search_sample.py` writes it again (`tests/test_search_model.py`
checks it when the model is fetched).
Since the lookup additions every block and list item has `lines`, every note `inbox`, and the vault has one "discuss
later" mark (`2026-10-23 2110 discuss Printing press`, about `Printing press#1`, no text).
