"""Phase P evaluation-only freeze over the existing development source copy.

No DB, credentials, providers, source fetching, or modification of Phase M.
Frozen GOLD labels are not returned as retrieval inputs.
"""
import json
from hashlib import sha256

from scripts.structural_descriptor_corpus import load_corpus
from services import structural_retrieval_entries_v2 as m
from services.structural_retrieval_entries import RetrievalEntryScope
from services.canary_contracts import CanaryError


def freeze(root):
    baseline = json.loads((root / '.codex_structural_4_1m/saved_1x_final.json').read_text(encoding='utf-8'))
    sidecar = json.loads((root / 'backend/fixtures/canary_mechanics_v1/real_corpus_retrieval_gold.json').read_text(encoding='utf-8'))
    gold_path = root / '.codex_real_corpus_v1/REAL_CORPUS_V1_EVAL_V1.json'
    if sha256(gold_path.read_bytes()).hexdigest() != sidecar['original_gold_sha256']:
        raise CanaryError('FROZEN_EVALUATION_CHANGED')
    if sidecar['implementation_hash'] != m._implementation_hash():
        raise CanaryError('FROZEN_M_IMPLEMENTATION_CHANGED')
    expected = sidecar['representation_pins']
    evidence, pins, resources, reconciliation = load_corpus(root)
    batches = {}
    for source_id, batch in sorted(evidence.items()):
        p = pins[source_id]
        scope = RetrievalEntryScope(revision=p.revision, crawl_id=p.crawl_id, crawl_version=p.crawl_version)
        value = m.build_retrieval_entries(batch, scope=scope)
        saved = expected.get(str(source_id))
        if saved is None or value.canonical_hash() != saved['batch_hash'] or scope.model_dump(mode='json') != saved['scope']:
            raise CanaryError('FROZEN_M_BATCH_CHANGED')
        batches[source_id] = value
    if set(map(str, batches)) != set(expected):
        raise CanaryError('FROZEN_CORPUS_INVENTORY_CHANGED')
    ordered_digest = sha256(''.join(b.canonical_hash() for b in batches.values()).encode()).hexdigest()
    if ordered_digest != baseline['identity_digest'] or m._implementation_hash() != baseline['v2_implementation_hash']:
        raise CanaryError('FROZEN_M_BASELINE_CHANGED')
    counts = dict(documents=len(batches), structural_entries=sum(len(b.entries) for b in batches.values()),
        searchable_atoms=sum(len(b.atoms) for b in batches.values()),
        structural_tokens=sum(e.token_count for b in batches.values() for e in b.entries))
    if counts['documents'] > 25 or counts['structural_entries'] > 1200 or counts['structural_tokens'] > 250000:
        raise CanaryError('STRUCTURAL_BUILD_BUDGET_HOLD')
    if any(e.token_count > 4000 for b in batches.values() for e in b.entries):
        raise CanaryError('INDIVIDUAL_ENTRY_BUDGET_HOLD')
    return batches, dict(counts=counts, ordered_batch_digest=ordered_digest,
        implementation_hash=m._implementation_hash(),
        baseline_file_sha256=sha256((root / '.codex_structural_4_1m/saved_1x_final.json').read_bytes()).hexdigest(),
        evaluation_sha256=sha256(gold_path.read_bytes()).hexdigest(),
        pins={str(k):v.scope.model_dump(mode='json') for k,v in batches.items()})


def sanity_entries(batches):
    """Deterministic structural variety; never reads questions or semantic GOLD."""
    all_entries = [(doc, e) for doc,b in sorted(batches.items()) for e in b.entries]
    selected, seen, tokens = [], set(), 0
    # Variety is typed atom kind + heading context, not product names or outcomes.
    def shape(doc, entry):
        atoms = {a.atom_key:a for a in batches[doc].atoms}
        return (tuple(sorted({atoms[x.atom_key].kind for x in entry.memberships})), bool(entry.context_token_count))
    for variety_only in (True, False):
        for doc, entry in all_entries:
            identity = (doc, entry.entry_key)
            if identity in {(d,e.entry_key) for d,e in selected}:
                continue
            signature = shape(doc, entry)
            if variety_only and signature in seen:
                continue
            if tokens + entry.token_count > 4000:
                continue
            selected.append((doc, entry))
            seen.add(signature)
            tokens += entry.token_count
            if len(selected) == 8:
                return tuple(selected)
    raise CanaryError('P1_EIGHT_ENTRY_BUDGET_HOLD')
