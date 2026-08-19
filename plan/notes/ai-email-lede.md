# The AI lede — shelved, kept whole

**Status: not in use.** The weekly emails ship a deterministic lede
(`lotg_support.email_summary`), which costs nothing and needs no key. This note
is the AI version, written and tested, removed from the shipping code on
2026-08-18 because the heuristic turned out to be good enough that paying for
the upgrade wasn't worth it. Everything needed to switch it back on is here.

## Why you might switch it back on

The heuristic is strong at the things you can compute: which place a line took,
which stat it was on, how much it resembles the rest of the week. It is blind to
the things you can only read for. Concretely, a model beats it when:

* **The story is a pattern, not a line.** "Three of Oliverwkw's four worst trades
  all involved the same player" is in the data, but not in any single line, and
  no scorer will find it.
* **A section is new.** The heuristic's prominence table is hand-maintained; a
  column added next season is neutral until someone classifies it. A model reads
  the name.
* **The week is genuinely mixed.** When there is no dominant block and no
  standout place, the heuristic falls back on counts. A model can still say what
  the week was about.

If the digest starts drawing "what actually happened this week?" replies, that is
the signal.

## What it cost

Estimated at ~2,800 input tokens for a 65-line digest (~4 chars/token; not
measured with `count_tokens`), two emails a week:

| model | config | per year |
|---|---|---|
| `claude-sonnet-5` | adaptive thinking, effort `low` | ~$0.85 |
| `claude-sonnet-5` | adaptive thinking, effort `medium` | ~$2.15 |
| `claude-opus-5` | adaptive thinking, effort `medium` | ~$5.37 |

**Use `claude-sonnet-5`.** Its $2/$10 per MTok launch pricing became the standard
price (the scheduled rise to $3/$15 was cancelled), which puts it at Haiku money
for a much stronger model. Do **not** reach for `claude-haiku-4-5` without
changing the request: `thinking: {"type": "adaptive"}` and `output_config.effort`
are not accepted on it, so a bare model swap 400s — and because the module is a
deliberate safe no-op, it would fail silently into the fallback forever.

## Turning it on

1. Create an API key at <https://platform.claude.com/settings/keys> and copy it
   (shown once).
2. Repo -> **Settings** -> **Secrets and variables** -> **Actions** -> **New
   repository secret**. Name it exactly `ANTHROPIC_API_KEY`, paste, **Add
   secret**.
3. Re-add `anthropic>=0.116.0` to `requirements.txt`.
4. Re-add the env pass-through to both workflows, next to the existing
   `PYTHONPATH`:

   ```yaml
   # .github/workflows/build.yml, "Build weekly digest"
   # .github/workflows/weekly_health_email.yml, "Send the weekly dataset-health email"
   ANTHROPIC_API_KEY: ${{ secrets.ANTHROPIC_API_KEY }}
   ```
5. Paste the code below back into `lib/lotg_support/email_summary.py` and have
   `build_intro` try `ai_summary` first, falling back to the deterministic lede:

   ```python
   def build_intro(sections, title, fallback=None, system=SYSTEM_DIGEST, use_ai=True):
       try:
           if not sections:
               return ""
           counted = (digest_lede(sections) if fallback is None else fallback)
           if use_ai:
               text = ai_summary(sections, title, counted, system=system)
               if text:
                   return text
           return counted
       except Exception as exc:               # never fail the email
           print(f"[lede] summary skipped ({type(exc).__name__}: {exc}).")
           return ""
   ```

To turn it off again, delete the secret — the code falls back on its own.

## The design, and why each piece is there

**The model never sees data.** It is handed the email's *own already-rendered
sentences* and nothing else — no frames, no rank maps, no value it would have to
interpret. The worst it can do is choose badly among true statements.

**Every draft is checked before it ships.** `is_grounded` requires every number
in the draft to already appear in the material it was given. Ordinals ("2nd") and
values ("103.3") fall out of the same regex, so a draft that promotes a 5th-place
move to "1st", rounds 103.3 to 103, or invents a count fails here rather than in
someone's inbox. The deterministic lede is passed in as context for the same
reason: the model is never asked to add anything up.

**It cannot stop an email.** No key, no package, an API error, a timeout, a
refusal, an over-long or preamble-y answer — every one returns `None` and the
deterministic lede ships. That property is the whole reason this was safe to try.

**Model output is HTML-escaped.** It is the only part of either email we did not
write.

## The code

### System prompts

```python
_LENGTH_RULE = f"""\
- At most {_MAX_SENTENCES} sentences, and fewer whenever fewer will do — one \
sentence is the right length for a quiet week. Length should track how much \
actually happened, not fill the allowance.
- Plain prose, no bullets, no heading, no markdown, no preamble like "Here is". \
Output only the paragraph itself."""

_GROUNDING_RULE = """\
- Every fact must come from the lines you are given. Do not use any number that \
does not appear there, do not compute new numbers, and do not name anything that \
is not named there."""

SYSTEM_DIGEST = f"""\
You write the opening paragraph of a fantasy-football league's weekly stats \
email. Below it sits the full list of every leaderboard move, which the reader \
can already see. Your job is to tell them which of those moves is worth caring \
about, so they know whether to read on.

Rules:
{_LENGTH_RULE}
{_GROUNDING_RULE}
- Lead with the single most notable item, then the shape of the rest. A 1st- or \
2nd-place move outranks a 5th-place one; a record or a milestone outranks a \
board shuffle; a stat people care about (points, O-Score, trades) outranks an \
obscure one.
- When a whole section moved for one obvious reason — dozens of draft-pick KTC \
values, say — say that as one clause rather than listing them.
- Write for the league members, not for an analyst. Name teams and players the \
way the lines do. No hype, no exclamation marks, no second-guessing the data."""

SYSTEM_AUDIT = f"""\
You write the opening paragraph of a weekly dataset-health email for the one \
person who maintains a fantasy-football stats pipeline. Below it sits the full \
audit: every finding, its detail lines, what upstream revised, and which weeks \
are missing injury captures. Your job is to tell the maintainer what needs a \
decision, so they know whether to open it now or after coffee.

Rules:
{_LENGTH_RULE}
{_GROUNDING_RULE}
- Lead with the thing most likely to be a real defect. A lost or renamed column, \
a build error, or a failing test outranks rows that moved; rows that moved for no \
stated reason outrank rows explained by an upstream revision or a merged code \
change; a missed injury week is the least urgent thing here.
- Say what moved and roughly how much, not every sheet by name. If many sheets \
moved for one stated reason, say the reason once.
- Do not diagnose, do not speculate about a cause the lines don't state, and do \
not recommend a fix. Do not reassure — if the findings are all explained, say \
so plainly and stop.
- Write to a peer who knows this pipeline. No hedging, no exclamation marks."""
```

### Guards

```python
def _numbers(text: str) -> set:
    """Numeric tokens, comma- and trailing-zero-normalised so "1,234" and "1234"
    and "1234.0" are the same number."""
    out = set()
    for raw in _NUM.findall(text or ""):
        v = raw.replace(",", "")
        if "." in v:
            v = v.rstrip("0").rstrip(".")
        out.add(v or "0")
    return out
def is_grounded(summary: str, source: str) -> bool:
    """Every number in `summary` also appears in `source`.

    Ordinals ("2nd") and values ("103.3") both fall out of the same regex, so a
    draft that promotes a 5th-place move to "1st", or rounds a value, fails here
    rather than in someone's inbox. The counted line is stated in `source` for
    the same reason — the model is never asked to add anything up."""
    return _numbers(summary).issubset(_numbers(source))


def _acceptable(summary: str, source: str) -> bool:
    s = (summary or "").strip()
    if not s or sentence_count(s) > _MAX_SENTENCES or len(s.split()) > _MAX_WORDS:
        return False
    # A model that answered with a list, a heading, or a preamble did not follow
    # the brief; the counted lede is better than a half-followed one.
    if s.startswith(("#", "-", "*", "Here", "Summary")) or "\n\n" in s:
        return False
    return is_grounded(s, source)
```

### The call

```python
def _prompt(sections: Sequence[Tuple[str, str, list]], title: str,
            totals: str = "") -> str:
    blocks = [f"Email header: {title}", f"Totals: {totals}", ""]
    budget = _MAX_LINES
    for name, lines in section_lines(sections):
        shown = lines[:budget]
        blocks.append(f"## {name} ({len(lines)})")
        blocks += shown
        if len(shown) < len(lines):
            blocks.append(f"(+{len(lines) - len(shown)} more lines in this section, "
                          f"not shown — do not claim to have seen every line)")
        blocks.append("")
        budget -= len(shown)
        if budget <= 0:
            break
    return "\n".join(blocks)


def ai_summary(sections: Sequence[Tuple[str, str, list]], title: str,
               totals: str = "", system: str = SYSTEM_DIGEST,
               model: Optional[str] = None) -> Optional[str]:
    """Claude's lede, or None if it isn't available or isn't usable.

    Never raises: a missing package, a missing key, a network failure, a refusal
    and an ungrounded draft are all the same outcome to the caller — no lede,
    use the counted one."""
    if not (os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN")):
        return None
    try:
        import anthropic
    except Exception:                             # noqa: BLE001 — absent or broken install
        return None
    source = _prompt(sections, title, totals)
    try:
        client = anthropic.Anthropic(timeout=_TIMEOUT_S)
        with client.messages.stream(
            model=model or _MODEL,
            max_tokens=2000,
            system=system,
            thinking={"type": "adaptive"},
            output_config={"effort": "medium"},
            messages=[{"role": "user", "content": source}],
        ) as stream:
            message = stream.get_final_message()
    except Exception as exc:                      # noqa: BLE001 — never fail the email
        print(f"[lede] AI summary unavailable ({type(exc).__name__}: {exc}) "
              f"— using the counted lede.")
        return None
    if getattr(message, "stop_reason", None) == "refusal":
        print("[lede] AI summary declined — using the counted lede.")
        return None
    text = " ".join(b.text for b in message.content
                    if getattr(b, "type", None) == "text").strip()
    if not _acceptable(text, source):
        print(f"[lede] AI summary rejected by the guards "
              f"({sentence_count(text)} sentence(s), {len(text.split())} words) "
              f"— using the counted lede.")
        return None
    # This string is interpolated straight into the email body. It is the only
    # part of either email we didn't write, so it gets escaped; an `&` or a `<`
    # in a model-written sentence would otherwise render as broken markup.
    return html.escape(text, quote=False)
```

## What was tested

`tests/test_email_summary.py` carried these before the removal; they are worth
restoring alongside the code:

* the AI path against a **stub client** (no key, no network) — pinning a current
  model, adaptive thinking, no `budget_tokens`, no sampling params, a timeout
  set, and the digest's own lines in the user turn;
* every failure mode falling back without raising (ungrounded draft, refusal, API
  error, no key);
* the grounding guard rejecting a promoted rank, a rounded value and a
  fabricated count, while accepting faithful numbers and comma/trailing-zero
  variants;
* HTML escaping of model output;
* the shape guard rejecting preambles, bullets and over-length drafts.

The live call was verified against the real SDK with an invalid key: it reached
the API and returned 401, confirming every parameter serialises. **No real
model-written lede was ever produced** — there were no credentials in the dev
environment, so the first run with the secret set is still the real test.
