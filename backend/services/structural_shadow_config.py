"""Server-only Phase 4.1F control. No request metadata or application DB access."""
from dataclasses import dataclass
import os
from pathlib import Path
import re


@dataclass(frozen=True)
class ShadowConfig:
    mode: str = 'off'
    scopes: frozenset[tuple[int, int]] = frozenset()
    model_cache: Path | None = None

    def __post_init__(self):
        if self.mode not in {'off', 'shadow', 'active'}:
            raise ValueError('Invalid STRUCTURAL_INGESTION_MODE')
        if self.mode == 'active':
            raise ValueError('Active structural ingestion is unavailable in Phase 4.1F')
        if len(self.scopes) > 1000 or any(
            len(p) != 2 or any(type(i) is not int or i <= 0 for i in p) for p in self.scopes
        ):
            raise ValueError('Invalid structural shadow allowlist')

    def allows(self, organization_id, bot_id):
        return self.mode == 'shadow' and (organization_id, bot_id) in self.scopes


def load_shadow_config(environ=None):
    env = os.environ if environ is None else environ
    raw = env.get('STRUCTURAL_SHADOW_ALLOWLIST', '')
    pairs = raw.split(',') if raw else []
    if len(raw) > 24000 or any(not re.fullmatch(r'[1-9]\d{0,9}:[1-9]\d{0,9}', p) for p in pairs):
        raise ValueError('Invalid STRUCTURAL_SHADOW_ALLOWLIST; expected org:bot pairs')
    return ShadowConfig(env.get('STRUCTURAL_INGESTION_MODE', 'off'),
                        frozenset(tuple(map(int, p.split(':'))) for p in pairs),
                        Path(env['STRUCTURAL_DOCLING_MODEL_CACHE']) if env.get('STRUCTURAL_DOCLING_MODEL_CACHE') else None)
