#
#  Copyright 2025 The InfiniFlow Authors. All Rights Reserved.
#
#  Licensed under the Apache License, Version 2.0 (the "License");
#  you may not use this file except in compliance with the License.
#  You may obtain a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
#  Unless required by applicable law or agreed to in writing, software
#  distributed under the License is distributed on an "AS IS" BASIS,
#  WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
#  See the License for the specific language governing permissions and
#  limitations under the License.
#
# Modified for Chatbot-SaaS: bounded adapter; see port manifest.

import copy
import json
import logging
from elasticsearch_dsl import Q, Search
from .doc_store import FusionExpr, MatchDenseExpr, MatchExpr, MatchTextExpr, OrderByExpr
from .float_utils import format_minimum_should_match_percent, get_float
from .runtime import PAGERANK_FLD, TAG_FLD

class ElasticsearchQuery:
    def __init__(self, client):
        self.es = client
        self.logger = logging.getLogger(__name__)

    def search(
        self,
        select_fields: list[str],
        highlight_fields: list[str],
        condition: dict,
        match_expressions: list[MatchExpr],
        order_by: OrderByExpr,
        offset: int,
        limit: int,
        index_names: str | list[str],
        knowledgebase_ids: list[str],
        agg_fields: list[str] | None = None,
        rank_feature: dict | None = None,
    ):
        """
        Refers to https://www.elastic.co/guide/en/elasticsearch/reference/current/query-dsl.html
        """
        if isinstance(index_names, str):
            index_names = index_names.split(",")
        assert isinstance(index_names, list) and len(index_names) > 0
        assert "_id" not in condition

        bool_query = Q("bool", must=[])
        condition = copy.deepcopy(condition)
        condition["kb_id"] = knowledgebase_ids
        for k, v in condition.items():
            if k == "available_int":
                if v == 0:
                    bool_query.filter.append(Q("range", available_int={"lt": 1}))
                else:
                    bool_query.filter.append(Q("bool", must_not=Q("range", available_int={"lt": 1})))
                continue
            if k == "id":
                if not v:
                    continue
                if isinstance(v, list):
                    bool_query.filter.append(Q("bool", should=[Q("terms", id=v), Q("terms", _id=v)], minimum_should_match=1))
                elif isinstance(v, str) or isinstance(v, int):
                    bool_query.filter.append(Q("bool", should=[Q("term", id=v), Q("term", _id=v)], minimum_should_match=1))
                continue
            if k == "must_not":
                if isinstance(v, dict):
                    for kk, vv in v.items():
                        if kk == "exists":
                            bool_query.must_not.append(Q("exists", field=vv))
                    continue
            if not v:
                continue
            if isinstance(v, list):
                bool_query.filter.append(Q("terms", **{k: v}))
            elif isinstance(v, str) or isinstance(v, int):
                bool_query.filter.append(Q("term", **{k: v}))
            else:
                raise Exception(f"Condition `{k!s}={v!s}` value type is {type(v)!s}, expected to be int, str or list.")

        s = Search()
        vector_similarity_weight = 0.5
        for m in match_expressions:
            if isinstance(m, FusionExpr) and m.method == "weighted_sum" and "weights" in m.fusion_params:
                assert (
                    len(match_expressions) == 3
                    and isinstance(match_expressions[0], MatchTextExpr)
                    and isinstance(match_expressions[1], MatchDenseExpr)
                    and isinstance(match_expressions[2], FusionExpr)
                )
                weights = m.fusion_params["weights"]
                vector_similarity_weight = get_float(weights.split(",")[1])
        for m in match_expressions:
            if isinstance(m, MatchTextExpr):
                minimum_should_match = (m.extra_options or {}).get("minimum_should_match", 0.0)
                if isinstance(minimum_should_match, float):
                    minimum_should_match = format_minimum_should_match_percent(minimum_should_match)
                bool_query.must.append(Q("query_string", fields=m.fields, type="best_fields", query=m.matching_text, minimum_should_match=minimum_should_match, boost=1))
                bool_query.boost = 1.0 - vector_similarity_weight

            elif isinstance(m, MatchDenseExpr):
                assert bool_query is not None
                similarity = 0.0
                if "similarity" in m.extra_options:
                    similarity = m.extra_options["similarity"]
                k = min(m.topn, 10000)
                if "num_candidates" in m.extra_options:
                    num_candidates = max(k, min(m.extra_options["num_candidates"], 10000))
                else:
                    num_candidates = min(k * 2, 10000)
                s = s.knn(
                    m.vector_column_name,
                    k,
                    num_candidates,
                    query_vector=list(m.embedding_data),
                    filter=bool_query.to_dict(),  # filter=_build_knn_filter_query(bool_query, vector_similarity_weight),
                    similarity=similarity,
                )

        if bool_query and rank_feature:
            for fld, sc in rank_feature.items():
                if fld != PAGERANK_FLD:
                    fld = f"{TAG_FLD}.{fld}"
                bool_query.should.append(Q("rank_feature", field=fld, linear={}, boost=sc))

        if bool_query:
            s = s.query(bool_query)
        for field in highlight_fields:
            s = s.highlight(field, fragment_size=50, number_of_fragments=5)

        if order_by:
            orders = list()
            for field, order in order_by.fields:
                order = "asc" if order == 0 else "desc"
                if field in ["page_num_int", "top_int"]:
                    order_info = {"order": order, "unmapped_type": "float", "mode": "avg", "numeric_type": "double"}
                elif field.endswith("_int") or field.endswith("_flt"):
                    order_info = {"order": order, "unmapped_type": "float"}
                elif field == "id":
                    continue  # id as "text", not a "keyword", order by it will cause error
                else:
                    order_info = {"order": order, "unmapped_type": "keyword"}
                orders.append({field: order_info})
            s = s.sort(*orders)
        if agg_fields:
            for fld in agg_fields:
                s.aggs.bucket(f"aggs_{fld}", "terms", field=fld, size=1000000)

        if offset < 0 or limit < 0 or (limit == 0 and not agg_fields) or offset + limit > 10000:
            raise ValueError("Bounded search window required")
        s = s[offset : offset + limit]
        if select_fields:
            s = s.source(select_fields)
        q = s.to_dict()
        vector_fields = [f for f in (select_fields or []) if f.endswith("_vec")]
        if vector_fields:
            q["fields"] = vector_fields
        res = self.es.search(index=index_names, body=q, track_total_hits=True)
        if res.get("timed_out"):
            raise RuntimeError("RETRIEVAL_FAILED")
        return res
