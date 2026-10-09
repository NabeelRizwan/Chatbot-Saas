from types import SimpleNamespace

from .client import RetrievalClient, RetrievalError
from .knowledge import document_record

PROFILE = {'provider': 'llamaindex', 'model': 'BAAI/bge-small-en-v1.5', 'version': 1, 'dimensions': 384}


def prepare(db, document, *, text, title, version, crawl_id, staging_id,
            check_cancelled=lambda: None, source_path=None, source_url=None):
    check_cancelled()
    result = RetrievalClient().request('/v1/prepare', document_record(document,
        text=text, title=title, version=version, crawl_id=crawl_id, source_url=source_url))
    check_cancelled()
    count = result.get('chunks')
    if type(count) is not int or not 0 < count <= 100000 or result.get('embeddings') != 0:
        raise RetrievalError('source_preparation_invalid')
    # Vector construction uses the entire promoted corpus, including cross-page
    # subject attribution. Do not report vectors that have not been built yet.
    return SimpleNamespace(specs=range(count), metadata=dict(PROFILE), embeddings=0)
