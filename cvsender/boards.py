"""Board tokens per ATS channel. Seeds a verified default list on first use."""
from __future__ import annotations

import yaml

from .config import BOARDS_PATH

DEFAULT = {
    "greenhouse": [
        # Israeli employers (verified live)
        "fireblocks", "riskified", "jfrog", "similarweb", "lightricks",
        "cybereason", "bigid", "melio", "pagaya", "yotpo", "axonius",
        "transmitsecurity", "saltsecurity", "orcasecurity", "catonetworks",
        "bringg", "via",
        # global boards that post new-grad / remote roles
        "stripe", "databricks", "figma", "coinbase", "dropbox", "robinhood",
        "gitlab", "cloudflare", "reddit", "discord", "asana", "twilio",
        "datadog", "elastic", "anthropic",
    ],
    "lever": ["mistral", "palantir"],
    "ashby": ["openai", "linear", "replit", "cohere", "ramp", "notion"],
    "comeet": [],
}


def load() -> dict:
    if not BOARDS_PATH.exists():
        BOARDS_PATH.write_text(yaml.safe_dump(DEFAULT, sort_keys=False,
                                              allow_unicode=True))
        return dict(DEFAULT)
    data = yaml.safe_load(BOARDS_PATH.read_text()) or {}
    return {k: (data.get(k) or []) for k in DEFAULT}
