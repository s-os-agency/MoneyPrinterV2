# MoneyPrinterV2 (Seif's fork) — plain-language README

## What this is
This is Seif's copy (a "fork") of **FujiwaraChoki/MoneyPrinterV2**, a Python app that automates online money-making tasks.

## Who it's for
People who want to experiment with automating social posts, short videos, and outreach. Upstream says it is for educational use.

## What it does today (according to upstream)
- **Twitter bot:** posts on a schedule.
- **YouTube Shorts:** makes and uploads short videos on a schedule.
- **Affiliate marketing:** pairs Amazon products with Twitter posts.
- **Local business outreach:** finds local businesses and sends them cold emails (this part needs the Go language installed).

**Seif's changes vs upstream** (made 21 March 2026):
- Added `.devcontainer/devcontainer.json`, a ready-made setup for opening the project in an online coding environment such as GitHub Codespaces.
- Added `.github/workflows/python-package-conda.yml`, an automatic GitHub check that installs and tests the Python package using Conda (a Python package manager). Whether it passes: not yet confirmed.

## How to run it
You need Python 3.12.
```
cp config.example.json config.json   # then fill in your own settings
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
python src/main.py
```

## Current status and known gaps
- Whether Seif has run it and with which accounts: not yet confirmed.
- Automating social media can break those platforms' rules. Check them before using it.

## Where things live
| Folder / file | What's in it |
|---|---|
| `src/` | The app (`src/main.py` starts it) |
| `scripts/` | Helper scripts |
| `config.example.json` | Sample settings to copy into `config.json` |
| `.devcontainer/` | Seif's coding-environment setup |
| `.github/workflows/` | Seif's automatic check |
| `LICENSE` | AGPL-3.0 |
