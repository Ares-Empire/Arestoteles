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
| `GET /vault` | `Vault`, the whole index. `ETag` = the vault commit; `If-None-Match` → `304`. |
| `GET /notes/{id}/source` | `{id, version, markdown}`: the note's body as Markdown (without frontmatter), for the free editor. |
| `POST /edits` `Edit` | `EditResult`. |
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
  version: string;                // git blob hash of the file: edits of the text name it
}

type Block =
  | { kind: "heading"; level: 2 | 3 | 4; text: Text; anchor: string }   // anchor: the heading text, as Obsidian links it
  | { kind: "paragraph"; text: Text }
  | { kind: "list"; ordered: boolean; items: { text: Text; depth: number }[] }   // depth 0 = top level
  | { kind: "positions"; ids: string[] }          // the "## My position" list: the app shows position cards here
  | { kind: "callout"; style: "claude" | "shaky" | "note"; title: Text | null; text: Text; index: number }
                                                  // index: position in Note.callouts; other callout types → "note"
  | { kind: "quote"; text: Text }
  | { kind: "embed"; note: string; anchor: string | null }   // ![[Note#Heading]]: the app shows that part
  | { kind: "table"; header: Text[]; rows: Text[][] }
  | { kind: "section_link"; note: string }        // a "→ [[Section page]]" line on its own
  | { kind: "rule" };

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
  | { op: "quick_note"; text: string };                          // a new Inbox note, status new, verbatim

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

## Language

Requests send `Accept-Language` (ares-empire/docs/LANGUAGES.md): German when the highest-weighted `de`/`en` tag is
German, otherwise English. Every answer sets `Content-Language: de|en` (and `Vary: Accept-Language`). The language
applies only to the server's own sentences: every `error`, and the warnings the server writes itself (check skipped).
The vault check's own warning lines, all vault content (titles, text, glossary), ids, codes and dates never change.

## Samples

`docs/samples/vault.json` (a small made-up vault, never Patrik's notes), `docs/samples/note-source.json`,
`docs/samples/edit-result.json`: used by the app's tests and sample mode. Keep them valid when the contract changes.
