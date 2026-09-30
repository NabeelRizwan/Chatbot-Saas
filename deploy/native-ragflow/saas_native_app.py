"""Private authenticated routes; no alternative account or chat system."""
from quart import request
from api.apps import login_required
from api.utils.api_utils import add_tenant_id_to_kwargs, get_result
from saas_native_core import NativeBoundaryError, POLICY, retrieve, manifest, source_integrity


@manager.route("/ready", methods=["GET"])
@login_required
@add_tenant_id_to_kwargs
async def ready(tenant_id):
    try:
        source_integrity()
        from common import settings
        ok = bool(settings.docStoreConn.es.ping())
        return get_result(data={"ready": ok, "tenant_id": tenant_id, "policy": POLICY})
    except Exception:
        return get_result(code=503, message="NATIVE_NOT_READY", data=None)


@manager.route("/retrieve", methods=["POST"])
@login_required
@add_tenant_id_to_kwargs
async def retrieval(tenant_id):
    try:
        source_integrity()
        return get_result(data=await retrieve(tenant_id, await request.get_json()))
    except NativeBoundaryError as error:
        return get_result(code=503, message=str(error), data=None)
    except Exception:
        return get_result(code=503, message="NATIVE_RETRIEVAL_FAILED", data=None)


@manager.route("/manifest", methods=["POST"])
@login_required
@add_tenant_id_to_kwargs
async def source_manifest(tenant_id):
    try:
        source_integrity()
        return get_result(data=manifest(tenant_id, await request.get_json()))
    except NativeBoundaryError as error:
        return get_result(code=503, message=str(error), data=None)
    except Exception:
        return get_result(code=503, message="NATIVE_MANIFEST_FAILED", data=None)
