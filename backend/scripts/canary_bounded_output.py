"""Public canary summaries are bounded metadata, never a vector transport."""
import json
import re

from services.canary_contracts import CanaryError

MAX_OUTPUT_BYTES = 65536
FORBIDDEN = {'embedding','embeddings','vector','vectors','coordinates','values','api_key',
             'database_url','dsn','environment','raw_response','receipts','vector_receipt',
             'final_prompt','raw_text','canonical_text','content','payload'}


def bounded_json(record, *, limit=MAX_OUTPUT_BYTES):
    def check(value,depth=0):
        if depth>12:
            raise CanaryError('OUTPUT_DEPTH_BOUND')
        if isinstance(value,dict):
            if len(value)>128:
                raise CanaryError('OUTPUT_OBJECT_BOUND')
            for key,item in value.items():
                if not isinstance(key,str) or key.lower() in FORBIDDEN:
                    raise CanaryError('UNSAFE_OUTPUT_FIELD')
                check(item,depth+1)
        elif isinstance(value,(list,tuple)):
            if len(value)>64:
                raise CanaryError('OUTPUT_ARRAY_BOUND')
            for item in value:check(item,depth+1)
        elif isinstance(value,str):
            if len(value)>512 or re.search(r'(?:AIza|AQ\.)[A-Za-z0-9_.-]{20,}|postgres(?:ql)?://',value):
                raise CanaryError('UNSAFE_OUTPUT_STRING')
        elif value is not None and type(value) not in (int,float,bool):
            raise CanaryError('UNSAFE_OUTPUT_TYPE')
    check(record)
    encoded=json.dumps(record,sort_keys=True,ensure_ascii=True,separators=(',',':'),allow_nan=False)
    if len(encoded.encode('utf-8'))>min(limit,MAX_OUTPUT_BYTES):
        raise CanaryError('OUTPUT_SIZE_BOUND')
    return encoded


def emit(record):
    print(bounded_json(record),flush=True)


def vector_summary(receipt):
    # Explicit fields, not asdict(receipt). Coordinates can never cross this API.
    return dict(input_hash=receipt.input_hash,profile_hash=receipt.profile_hash,
        vector_hash=receipt.vector_hash,dimensions=len(receipt.vector),canonical_bytes=3072,
        provider_attempt=receipt.provider_attempt)
