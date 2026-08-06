# AIxposed

```
      /\_/\
     ( o.o )   "your 'private' share link was never private, king"
      > ^ <
     /|   |\
    (_|   |_)
```

**AIxposed** by **N3 Sec** — we find public AI chat shares so you don't have to pretend Google invented OSINT.

> "anyone with the link can view"  
> yeah bro. anyone. including this cat. including the Wayback Machine. including your future self at 3am screaming.

No LinkedIn-speak. No "leverage synergies." No purple gradient landing page energy.  
Just UUIDs, CDX junk, DuckDuckGo dorks, and a CSV that either makes you laugh or ruin someone's afternoon.

---

## what even is this

People hit **Share** on Claude / ChatGPT / Grok / Gemini / DeepSeek thinking it's a secret handshake.

It's a public URL.

We:

1. dig the open web + archives for `/share/` crumbs
2. bounce between domains so rate limits don't catch the L
3. poke UUID-shaped holes when the mood is spicy
4. dump `title,link` into a CSV like it's 2009 and XMLRPC still mattered

```
      /\_/\
     ( -.- )  zzz... indexing your "confidential" prompt about crypto...
      > ^ <
```

---

## install (touch grass optional)

```powershell
cd d:\Tools\CLAUDE-APPROVED
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```

---

## run it (zero brain cells required)

```powershell
# yeet everything. all providers. interleaved. go. (no banner, we have taste)
python -m aixposed

# TOPIC SEARCH — dorks + title/body filter. only matching shares hit the CSV
python -m aixposed search -q "stanford HCAI" --out hits.csv
python -m aixposed -q "ransomware" --providers claude,chatgpt --after 2024-06-01

# hunt Claude harder (extra dorks) + unindexed brute
python -m aixposed --providers claude --sources search,cdx,brute --brute-attempts 2000 -q "artifact"

# neighbor-probe around known IDs (not just whatever Google indexed)
python -m aixposed --sources brute --seed-file ids.txt --brute-attempts 1000 --providers chatgpt,claude

# raw archive dump, skip live checks
python -m aixposed --sources cdx --no-verify --limit 60 --out raw.csv

python -m aixposed plugins
python -m aixposed --banner
```

### knobs for the terminally online


| Flag | Default | Vibes |
|------|---------|-------|
| `--providers` | `all` | who we haunt |
| `--sources` | `search,cdx` | where we dig (`brute` = unindexed UUIDs) |
| `--limit` | `2000` | max unique links total (live-printed) |
| `-q` / `--query` | off | keep ONLY shares whose title/body match (AND tokens) |
| `--after` / `--before` | off | date filter `YYYY-MM-DD` (from share metadata when present) |
| `--brute-attempts` | `500` | how hard we yeet UUIDs into the void |
| `--seed-file` | off | known IDs/URLs + nearby UUID neighbors |
| `--no-verify` | off | skip live checks |
| `--live-only` | off | drop dead/revoked |
| `--banner` | off | N3 Sec ASCII, opt-in |

> **Claude scarce?** Indexes nuked a lot of `/share` pages. Use `search -q "..."` + `--sources search,cdx,brute` and crank `--brute-attempts`. Brute is the "not indexed" path.
>
> **Titles:** Grok `og:title`, ChatGPT `pageTitle` / react-router stream, cleaned of `ChatGPT -` / `| Shared Grok Conversation` junk.
>
> CSV columns: `title,link,provider,source,share_id,status,created_at`


---

## plug-and-play (actually though)

Drop a file. Don't open a PR asking if you "should modularize the architecture."

### new provider → `aixposed/plugins/providers/skynet.py`

```python
import re
from aixposed.plugins.base import ProviderPlugin

PROVIDER = ProviderPlugin(
    key="skynet",
    name="Skynet",
    url_template="https://skynet.ai/share/{id}",
    discovery_patterns=("skynet.ai/share/",),
    url_regex=re.compile(r"https?://skynet\.ai/share/([A-Za-z0-9_-]+)", re.I),
)
```

### new source → `aixposed/plugins/sources/trashfire.py`

Export `SOURCE` with `.key`, `.name`, and `async def discover(self, ctx)`.  
If it works, ship it. If it doesn't, blame DNS.

```
      /\_/\
     ( >_< )  *knocks coffee onto keyboard*
      > ^ <     "it's a feature"
```

---

## rate-limit evasion (polite chaos)

We don't send 500 love letters to `claude.ai` then casually stroll over to ChatGPT.

- round-robin providers  
- round-robin sources  
- verify shuffled by host  
- UA + Accept-Language roulette  
- backoff when the cloud says "bro stop" (429/403/503)

If you still get banned: skill issue. touch the `--delay`.

---

## CSV go brrr

```
title,link,provider,source,share_id
```

That's it. No dashboard. No SaaS. No "insights."  
Open it in Excel like a goblin.

---

## file tree (for people who read READMEs???)

```
aixposed/
  banner.py       # N3 Sec drip
  evasion.py      # don't get clapped by rate limits
  engine.py       # the blender
  cli.py          # buttons
  plugins/
    providers/    # PROVIDER = ProviderPlugin(...)
    sources/      # SOURCE = something cursed
```

---

## disclaimer

Public shares only. Don't be weird. Don't be illegal.  
If someone pasted their API keys into a "private" share — that was a choice.  
We're just the cat watching from the windowsill.

```
      /\_/\
     ( ^.^ )   N3 Sec was here
      > ^ <
        |
     ___|___
    /       \   AIxposed — because "anyone with the link" means anyone.
```

