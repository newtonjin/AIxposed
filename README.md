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

# same energy, more typing
python -m aixposed discover --providers all --sources search,cdx --out aixposed.csv

# feel dangerous
python -m aixposed discover --sources search,cdx,commoncrawl,brute --brute-attempts 500

# only the main characters
python -m aixposed discover --providers claude,chatgpt --out shares.csv

# what plugins even loaded lol
python -m aixposed plugins

# OPTIONAL drip — banner is OFF by default, you gotta ask for it lol
python -m aixposed --banner --limit 60 --out test.csv

# or just stare at the logo like it's a personality
python -m aixposed banner
```

### knobs for the terminally online


| Flag             | Default      | Vibes                                                 |
| ---------------- | ------------ | ----------------------------------------------------- |
| `--providers`    | `all`        | who we haunt                                          |
| `--sources`      | `search,cdx` | where we dig                                          |
| `--delay`        | `0.7`        | chill pill for the wire                               |
| `--host-gap`     | `1.1`        | don't spam the same host like a bot (ironic, we know) |
| `--concurrency`  | `6`          | parallel chaos, still interleaved                     |
| `--no-verify`    | off          | skip titles, live your truth                          |
| `--banner`       | off          | N3 Sec ASCII flex. opt-in only. main character mode.  |
| `--no-rotate-ua` | off          | one UA forever. coward.                               |


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

