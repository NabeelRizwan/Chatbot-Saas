"""Explicit target validation only. Does not connect or consult environment.

A later authorized runner must verify this allowlist before opening a connection,
then verify the pre-provisioned ownership marker on that connection. No discovery.
"""
from sqlalchemy.engine import make_url
from services.canary_contracts import Value, Digest, Name, Approval, CanaryError
from services.structural_chunking import digest


class DisposableTarget(Value):
    host_database_fingerprint: Digest
    ownership_marker: Name
    approval_reference: Name


def validate_target(url_text, target: DisposableTarget, approval: Approval):
    try:
        url=make_url(url_text)
        if url.drivername not in ('postgres','postgresql','postgresql+psycopg2') or not url.host or not url.database or not url.port:
            raise ValueError()
        fingerprint=digest({'host':url.host.lower(),'port':url.port,'database':url.database})
        if (approval.environment!='disposable_test' or target.host_database_fingerprint!=fingerprint or
            approval.database_identity!=fingerprint or target.ownership_marker!=approval.ownership_marker or
            target.approval_reference!=approval.operator_reference):
            raise ValueError()
    except Exception:
        raise CanaryError('EXPLICIT_DISPOSABLE_TARGET_REFUSED') from None
    return fingerprint  # no URL/user/password returned or logged
