"""Portable private object storage for durable knowledge-source uploads.

The ingestion application depends on this small port. Local disk is an
explicit development/test adapter; production uses an S3-compatible adapter.
Hosting-vendor mapping belongs in deployment documentation.
"""
from __future__ import annotations

import os
import shutil
import tempfile
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any, Iterator, Mapping, Protocol
from uuid import uuid4

BACKEND_DIR = Path(__file__).resolve().parents[1]


class ObjectStorageError(RuntimeError):
    """A customer-safe storage-boundary failure."""


@dataclass(frozen=True)
class ObjectMetadata:
    key: str
    size: int
    content_type: str | None = None
    etag: str | None = None


class ObjectStorage(Protocol):
    provider_name: str

    def put(
        self,
        key: str,
        data: bytes,
        *,
        content_type: str | None = None,
        metadata: Mapping[str, str] | None = None,
    ) -> ObjectMetadata: ...

    def download_to_temp(self, key: str) -> Iterator[str]: ...

    def delete(self, key: str) -> bool: ...

    def exists(self, key: str) -> bool: ...

    def metadata(self, key: str) -> ObjectMetadata: ...

    def healthcheck(self) -> bool: ...


def normalize_object_key(key: str) -> str:
    """Return a safe relative POSIX key or reject traversal/absolute paths."""
    raw = str(key or "").replace("\\", "/").strip()
    if raw.startswith("/") or (len(raw) >= 2 and raw[1] == ":"):
        raise ObjectStorageError("Invalid object-storage key.")
    normalized = raw.strip("/")
    path = PurePosixPath(normalized)
    if not normalized or path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
        raise ObjectStorageError("Invalid object-storage key.")
    return path.as_posix()


def build_source_object_key(
    organization_id: int,
    bot_id: int,
    extension: str,
    *,
    document_token: str | None = None,
) -> str:
    suffix = extension.lower() if extension.startswith(".") else f".{extension.lower()}"
    if suffix not in {".pdf", ".txt", ".docx"}:
        raise ObjectStorageError("Unsupported knowledge-source extension.")
    token = document_token or uuid4().hex
    return normalize_object_key(
        f"organizations/{int(organization_id)}/bots/{int(bot_id)}/documents/{token}/source{suffix}"
    )


def validate_source_object_ownership(key: str, organization_id: int, bot_id: int) -> str:
    """Reject a DB object reference that points outside its tenant/bot prefix."""
    safe_key = normalize_object_key(key)
    expected_prefix = f"organizations/{int(organization_id)}/bots/{int(bot_id)}/"
    if not safe_key.startswith(expected_prefix):
        raise ObjectStorageError("The source object does not belong to this bot and organization.")
    return safe_key


class LocalObjectStorage:
    provider_name = "local"

    def __init__(self, root: str | Path | None = None):
        configured = root or os.getenv("OBJECT_STORAGE_LOCAL_DIR") or BACKEND_DIR / "storage" / "knowledge"
        configured_path = Path(configured)
        self.root = (
            configured_path if configured_path.is_absolute() else BACKEND_DIR / configured_path
        ).resolve()

    def _path(self, key: str) -> Path:
        candidate = (self.root / Path(*normalize_object_key(key).split("/"))).resolve()
        try:
            candidate.relative_to(self.root)
        except ValueError as exc:
            raise ObjectStorageError("Object key escaped the configured storage root.") from exc
        return candidate

    def put(
        self,
        key: str,
        data: bytes,
        *,
        content_type: str | None = None,
        metadata: Mapping[str, str] | None = None,
    ) -> ObjectMetadata:
        del metadata
        target = self._path(key)
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary = target.with_name(f".{target.name}.{uuid4().hex}.tmp")
        try:
            temporary.write_bytes(data)
            temporary.replace(target)
        except OSError as exc:
            temporary.unlink(missing_ok=True)
            raise ObjectStorageError("Unable to persist the uploaded source object.") from exc
        return ObjectMetadata(key=normalize_object_key(key), size=len(data), content_type=content_type)

    @contextmanager
    def download_to_temp(self, key: str) -> Iterator[str]:
        source = self._path(key)
        if not source.is_file():
            raise ObjectStorageError("The uploaded source object is unavailable.")
        suffix = source.suffix
        fd, temporary_name = tempfile.mkstemp(prefix="knowledge-", suffix=suffix)
        os.close(fd)
        temporary = Path(temporary_name)
        try:
            shutil.copyfile(source, temporary)
            yield str(temporary)
        finally:
            temporary.unlink(missing_ok=True)

    def delete(self, key: str) -> bool:
        target = self._path(key)
        if not target.is_file():
            return False
        target.unlink()
        parent = target.parent
        while parent != self.root:
            try:
                parent.rmdir()
            except OSError:
                break
            parent = parent.parent
        return True

    def exists(self, key: str) -> bool:
        return self._path(key).is_file()

    def metadata(self, key: str) -> ObjectMetadata:
        target = self._path(key)
        if not target.is_file():
            raise ObjectStorageError("The uploaded source object is unavailable.")
        return ObjectMetadata(key=normalize_object_key(key), size=target.stat().st_size)

    def healthcheck(self) -> bool:
        try:
            self.root.mkdir(parents=True, exist_ok=True)
            return self.root.is_dir()
        except OSError:
            return False


class S3CompatibleObjectStorage:
    provider_name = "s3"

    def __init__(
        self,
        *,
        endpoint: str | None,
        bucket: str,
        access_key_id: str,
        secret_access_key: str,
        region: str,
    ):
        try:
            import boto3
            from botocore.config import Config
        except ImportError as exc:
            raise ObjectStorageError("The S3 object-storage dependency is not installed.") from exc
        self.bucket = bucket
        self._client = boto3.client(
            "s3",
            endpoint_url=endpoint or None,
            aws_access_key_id=access_key_id,
            aws_secret_access_key=secret_access_key,
            region_name=region,
            config=Config(signature_version="s3v4", retries={"max_attempts": 2, "mode": "standard"}),
        )

    def put(
        self,
        key: str,
        data: bytes,
        *,
        content_type: str | None = None,
        metadata: Mapping[str, str] | None = None,
    ) -> ObjectMetadata:
        safe_key = normalize_object_key(key)
        kwargs: dict[str, Any] = {
            "Bucket": self.bucket,
            "Key": safe_key,
            "Body": data,
            "Metadata": dict(metadata or {}),
        }
        if content_type:
            kwargs["ContentType"] = content_type
        try:
            result = self._client.put_object(**kwargs)
        except Exception as exc:
            raise ObjectStorageError("Unable to persist the uploaded source object.") from exc
        return ObjectMetadata(
            key=safe_key,
            size=len(data),
            content_type=content_type,
            etag=str(result.get("ETag") or "").strip('"') or None,
        )

    @contextmanager
    def download_to_temp(self, key: str) -> Iterator[str]:
        safe_key = normalize_object_key(key)
        suffix = PurePosixPath(safe_key).suffix
        fd, temporary_name = tempfile.mkstemp(prefix="knowledge-", suffix=suffix)
        os.close(fd)
        temporary = Path(temporary_name)
        try:
            self._client.download_file(self.bucket, safe_key, str(temporary))
        except Exception as exc:
            temporary.unlink(missing_ok=True)
            raise ObjectStorageError("Unable to download the uploaded source object.") from exc
        try:
            yield str(temporary)
        finally:
            temporary.unlink(missing_ok=True)

    def delete(self, key: str) -> bool:
        safe_key = normalize_object_key(key)
        existed = self.exists(safe_key)
        try:
            self._client.delete_object(Bucket=self.bucket, Key=safe_key)
        except Exception as exc:
            raise ObjectStorageError("Unable to delete the uploaded source object.") from exc
        return existed

    def exists(self, key: str) -> bool:
        try:
            self._client.head_object(Bucket=self.bucket, Key=normalize_object_key(key))
            return True
        except Exception as exc:
            response = getattr(exc, "response", {}) or {}
            status = (response.get("ResponseMetadata") or {}).get("HTTPStatusCode")
            if status == 404:
                return False
            raise ObjectStorageError("Unable to inspect the uploaded source object.") from exc

    def metadata(self, key: str) -> ObjectMetadata:
        safe_key = normalize_object_key(key)
        try:
            result = self._client.head_object(Bucket=self.bucket, Key=safe_key)
        except Exception as exc:
            raise ObjectStorageError("Unable to inspect the uploaded source object.") from exc
        return ObjectMetadata(
            key=safe_key,
            size=int(result.get("ContentLength") or 0),
            content_type=result.get("ContentType"),
            etag=str(result.get("ETag") or "").strip('"') or None,
        )

    def healthcheck(self) -> bool:
        try:
            self._client.head_bucket(Bucket=self.bucket)
            return True
        except Exception:
            return False


def configured_object_storage_provider(environment: Mapping[str, str] | None = None) -> str:
    env = environment or os.environ
    default = "s3" if env.get("APP_ENV", "development").lower() in {"production", "prod"} else "local"
    return (env.get("OBJECT_STORAGE_PROVIDER") or default).lower().strip()


def validate_object_storage_config(environment: Mapping[str, str]) -> None:
    provider = configured_object_storage_provider(environment)
    production = environment.get("APP_ENV", "development").lower() in {"production", "prod"}
    if provider not in {"local", "s3"}:
        raise RuntimeError("OBJECT_STORAGE_PROVIDER must be 'local' or 's3'.")
    if production and provider != "s3":
        raise RuntimeError("Production requires OBJECT_STORAGE_PROVIDER=s3; local upload storage is not allowed.")
    if provider == "s3":
        required = (
            "OBJECT_STORAGE_BUCKET",
            "OBJECT_STORAGE_ACCESS_KEY_ID",
            "OBJECT_STORAGE_SECRET_ACCESS_KEY",
            "OBJECT_STORAGE_REGION",
        )
        missing = [name for name in required if not environment.get(name)]
        if missing:
            raise RuntimeError(f"Missing S3-compatible object-storage configuration: {', '.join(missing)}")


def get_object_storage(provider_name: str | None = None) -> ObjectStorage:
    selected = (provider_name or configured_object_storage_provider()).lower().strip()
    if selected == "local":
        if os.getenv("APP_ENV", "development").lower() in {"production", "prod"}:
            raise ObjectStorageError("Local object storage is disabled in production.")
        return LocalObjectStorage()
    if selected == "s3":
        validate_object_storage_config({**os.environ, "OBJECT_STORAGE_PROVIDER": "s3"})
        return S3CompatibleObjectStorage(
            endpoint=os.getenv("OBJECT_STORAGE_ENDPOINT"),
            bucket=os.environ["OBJECT_STORAGE_BUCKET"],
            access_key_id=os.environ["OBJECT_STORAGE_ACCESS_KEY_ID"],
            secret_access_key=os.environ["OBJECT_STORAGE_SECRET_ACCESS_KEY"],
            region=os.environ["OBJECT_STORAGE_REGION"],
        )
    raise ObjectStorageError("Unsupported object-storage provider.")
