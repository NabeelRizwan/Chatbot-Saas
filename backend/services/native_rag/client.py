"""Operator-configured native API; no endpoints or permissions from chat input.

Uses RAGFlow v0.27.2's official dataset/document APIs and its bounded native
candidate adapter. No retries of mutations whose outcome is unknown.
"""
import re
import httpx
from .config import NativeConfig, NativeRagError, SEARCH_POLICY


def identifier(value):
    if not isinstance(value, str) or not re.fullmatch(r"[0-9a-f]{16,64}", value):
        raise NativeRagError("native_identity_invalid")
    return value


class NativeClient:
    def __init__(self, config=None, *, transport=None):
        self.config = config or NativeConfig.from_env()
        self.transport = transport

    def request(self, method, path, *, body=None, params=None, files=None):
        if not path.startswith(("/api/v1/", "/v1/saas_native/")) or ".." in path:
            raise NativeRagError("native_route_invalid")
        try:
            with httpx.Client(base_url=self.config.url, timeout=self.config.timeout,
                              trust_env=False, follow_redirects=False, transport=self.transport) as client:
                response = client.request(method, path, json=body, params=params, files=files,
                    headers={"Authorization": "Bearer " + self.config.token})
        except httpx.HTTPError:
            raise NativeRagError("native_service_unavailable") from None
        if response.status_code != 200 or len(response.content) > 32 * 1024 * 1024:
            raise NativeRagError("native_request_failed")
        try:
            value = response.json()
            if not isinstance(value, dict) or type(value.get("code")) is not int or value["code"] != 0:
                raise ValueError()
            return value["data"]
        except (ValueError, KeyError):
            raise NativeRagError("native_response_invalid") from None

    def search(self, query, dataset, documents):
        identifier(dataset)
        if not documents:
            return []
        if len(documents) > 10000 or len(set(documents)) != len(documents):
            raise NativeRagError("native_document_scope_invalid")
        for doc in documents:
            identifier(doc)
        result = self.request("POST", "/v1/saas_native/retrieve", body={
            "question": query, "dataset_id": dataset, "document_ids": documents})
        if (not isinstance(result, dict) or result.get("policy") != SEARCH_POLICY or
                result.get("tenant_id") != self.config.tenant or result.get("dataset_id") != dataset or
                not isinstance(result.get("chunks"), list) or len(result["chunks"]) > 128):
            raise NativeRagError("native_search_contract_invalid")
        return result["chunks"]

    def manifest(self, dataset, document):
        return self.request("POST", "/v1/saas_native/manifest", body={
            "dataset_id": identifier(dataset), "document_id": identifier(document)})

    def health(self):
        value = self.request("GET", "/v1/saas_native/ready")
        return (isinstance(value, dict) and value.get("policy") == SEARCH_POLICY and
                value.get("tenant_id") == self.config.tenant and value.get("ready") is True)
