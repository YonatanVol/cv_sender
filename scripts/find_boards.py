"""Find which ATS each company actually uses, by asking every public API.

    ./.venv/bin/python scripts/find_boards.py            # verify + report
    ./.venv/bin/python scripts/find_boards.py --write    # also update boards.yaml

Guessing tokens by hand is how the board list stayed tiny. This tries each
candidate slug against every channel and keeps only the ones that return real
postings, so boards.yaml is always verified rather than hopeful.
"""
from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import yaml

from cvsender import boards
from cvsender.channels.registry import BUILDERS

# Israeli tech employers + global companies that hire juniors remotely.
CANDIDATES = """
fireblocks riskified jfrog similarweb lightricks cybereason bigid melio pagaya
yotpo axonius transmitsecurity saltsecurity orcasecurity catonetworks bringg via
monday wix fiverr payoneer lemonade taboola outbrain ironsource playtika
verbit hibob papayaglobal papaya-global gong walkme cellebrite tipalti rapyd
forter nayax kaltura optibus deel snyk aqua-security aquasec wiz island armis
claroty perimeterx cato descope frontegg jit unit21 next-insurance bizzabo
augury vast-data vastdata run-ai runai deci datagen explorium anodot
trigo cognyte allot radware checkpoint cyberark imperva varonis
lusha similarwebisrael zesty granulate speedb redis
""".split()


async def probe(channel: str, token: str) -> int:
    """How many postings this channel returns for this token (0 = not it)."""
    try:
        adapter = BUILDERS[channel]([token])
        jobs = await adapter.discover({})
        return len(jobs)
    except Exception:
        return 0


async def main(write: bool) -> int:
    found: dict[str, dict[str, int]] = {c: {} for c in BUILDERS}
    sem = asyncio.Semaphore(8)

    async def one(channel: str, token: str) -> None:
        async with sem:
            n = await probe(channel, token)
            if n:
                found[channel][token] = n

    await asyncio.gather(*(one(c, t) for c in BUILDERS for t in CANDIDATES))

    total = 0
    for channel, hits in found.items():
        if not hits:
            continue
        print(f"\n{channel}:")
        for token, n in sorted(hits.items(), key=lambda kv: -kv[1]):
            print(f"  {token:22} {n:4} postings")
            total += n
    print(f"\n{sum(len(h) for h in found.values())} boards, {total} postings")

    if write:
        cfg = boards.load()
        added = 0
        for channel, hits in found.items():
            have = set(cfg.get(channel) or [])
            for token in hits:
                if token not in have:
                    cfg.setdefault(channel, []).append(token)
                    added += 1
        boards.BOARDS_PATH.write_text(
            yaml.safe_dump(cfg, sort_keys=False, allow_unicode=True))
        print(f"boards.yaml updated: +{added} board(s)")
    return 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--write", action="store_true", help="update data2/boards.yaml")
    sys.exit(asyncio.run(main(ap.parse_args().write)))
