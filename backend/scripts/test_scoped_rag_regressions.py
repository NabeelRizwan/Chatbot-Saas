"""Offline RAG/auth/widget regressions. Never connects to the configured DB.

Run from backend: python -B scripts/test_scoped_rag_regressions.py
"""
from contextlib import ExitStack
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from database import connection


SUITES = [
    "test_canary_vector_f32",
    "test_canary_postgres_guard",
    "test_canary_stage_a",
    "test_structural_retrieval_headings",
    "test_structural_retrieval_entries",
    "test_structural_resource_descriptors",
    "test_structural_identity_study",
    "test_structural_selection_v2",
    "test_structural_packing_analysis",
    "test_structural_shadow",
    "test_structural_chunk_serializer",
    "test_structural_docling_adapter",
    "test_structural_text_adapter",
    "test_structural_repository",
    "test_structural_contracts",
    "test_planner_intent_contract",
    "test_generation_model_defaults",
    "test_phase37_compatibility_evidence",
    "test_phase37_quantity_context_closure",
    "test_phase37_manual_regressions",
    "test_reviewer_structured_output",
    "test_phase36_acceptance_followthrough",
    "test_phase36_completeness",
    "test_phase36_boundaries",
    "test_phase36_verifier",
    "test_phase35_live_repair",
    "test_phase35_boundaries",
    "test_phase34_acceptance",
    "test_candidate_free_semantic_gaps", "test_semantic_gap_handoff",
    "test_resource_semantic_gaps", "test_phase33_acceptance",
    "test_resource_probe_understanding", "test_resource_probe_benchmark", "test_resource_probe_handoff",
    "test_phase31_remote_harness",
    "test_generalized_rag_core",
    "test_phase2_remote_harness",
    "test_phase_1_6_1_context_budget",
    "test_phase2_hybrid_retrieval",
    "test_phase_1_6_post_live_correctness",
    "test_retrieval_candidate_recall", "test_retrieval_safety_gates",
    "test_scoped_rag_architecture", "test_phase_l_ecommerce_retrieval",
    "test_phase_l2_conversational_field_retrieval", "test_phase_l3_multi_entity_conversational_rag",
    "test_phase_l4_widget_latency_delivery", "test_content_subject_resolution",
    "test_typo_identity_resolution", "test_exclusion_entity_resolution", "test_explicit_field_completeness",
    "test_qualifier_comparison_resolution", "test_qualification_context_preservation",
    "test_ordered_field_evidence", "test_required_evidence_retention", "test_human_answer_quality",
    "test_phase_e_widget_streaming_parity", "test_exact_page_crawl_mode",
    "test_phase_a_tenant_chat_security", "test_phase_a2_stop_ship_security",
    "test_phase_i_streaming_sources", "test_final_production_architecture",
    "test_resource_discovery", "test_resource_discovery_safety",
    "test_resource_postgres_harness", "test_resource_discovery_benchmark",
    "test_resource_discovery_scale", "test_resource_discovery_historical",
]
CACHE_CASES = [
    "test_e_tenant_safe_cache_keys", "test_f_and_g_tenant_and_bot_isolation",
    "test_h_knowledge_version_isolation", "test_i_and_j_knowledge_promotion_and_failed_crawl",
    "test_m_redis_outage_fallback",
]


def main():
    with ExitStack() as stack:
        stack.enter_context(patch.object(connection.engine, "connect", side_effect=AssertionError("Configured DB forbidden in offline tests")))
        stack.enter_context(patch("services.rag_planning.generate_auxiliary", side_effect=TimeoutError("Offline planner fallback")))
        stack.enter_context(patch("httpx.Client.send", side_effect=AssertionError("Live HTTP forbidden in offline tests")))
        stack.enter_context(patch("httpx.AsyncClient.send", side_effect=AssertionError("Live HTTP forbidden in offline tests")))
        stack.enter_context(patch("requests.sessions.Session.request", side_effect=AssertionError("Live HTTP forbidden in offline tests")))
        names = SUITES + ["test_db_pool_cache_suite.TestDBPoolAndTenantCacheSuite." + name for name in CACHE_CASES]
        result = unittest.TextTestRunner(verbosity=1).run(unittest.defaultTestLoader.loadTestsFromNames(names))
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    raise SystemExit(main())
