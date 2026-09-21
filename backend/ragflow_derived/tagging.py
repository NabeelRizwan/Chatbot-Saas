# Copyright 2026 The InfiniFlow Authors. All Rights Reserved.
# Licensed under the Apache License, Version 2.0.
# Modified for Chatbot-SaaS: explicit scoped imports; see port manifest.
import json
from .full_runtime import settings

def label_question(question, kbs):
    from ragflow_derived.full_runtime import KnowledgebaseService
    from ragflow_derived.upstream.graphrag.utils import get_tags_from_cache, set_tags_to_cache

    tags = None
    tag_kb_ids = []
    for kb in kbs:
        if kb.parser_config.get("tag_kb_ids"):
            tag_kb_ids.extend(kb.parser_config["tag_kb_ids"])
    if tag_kb_ids:
        all_tags = get_tags_from_cache(tag_kb_ids)
        if not all_tags:
            all_tags = settings.retriever.all_tags_in_portion(kb.tenant_id, tag_kb_ids)
            set_tags_to_cache(tags=all_tags, kb_ids=tag_kb_ids)
        else:
            all_tags = json.loads(all_tags)
        tag_kbs = KnowledgebaseService.get_by_ids(tag_kb_ids)
        if not tag_kbs:
            return tags
        tags = settings.retriever.tag_query(question, list(set([kb.tenant_id for kb in tag_kbs])), tag_kb_ids, all_tags, kb.parser_config.get("topn_tags", 3))
    return tags


if __name__ == "__main__":
    import sys

    def dummy(prog=None, msg=""):
        pass

    chunk(sys.argv[1], from_page=0, to_page=10, callback=dummy)

