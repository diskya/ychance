from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from typing import Any, Callable

from audit import AuditLog
from rawstore import Provenance, RawStore


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class RawStoreWriter:
    put_llm_response: Callable[..., str]

    def __init__(self, store: RawStore, audit: AuditLog) -> None:
        if not isinstance(store, RawStore):
            raise TypeError("store must be a RawStore")
        if not isinstance(audit, AuditLog):
            raise TypeError("audit must be an AuditLog")
        self.__audit = audit
        reader = store._issue_reader()

        def put_llm_response(
            *,
            body: bytes,
            model_id: str,
            prompt_hash: str,
            params_hash: str,
            fetch_time: datetime,
        ) -> str:
            fetch_utc = _ensure_utc(fetch_time)
            if not isinstance(body, (bytes, bytearray, memoryview)):
                raise TypeError("body must be bytes-like")
            body_bytes = bytes(body)
            expected_hash = hashlib.sha256(body_bytes).hexdigest()
            record: dict[str, Any] = {
                "category": "LLMWrite",
                "stage": "access_writer",
                "envelope": {},
                "model_id": model_id,
                "prompt_hash": prompt_hash,
                "params_hash": params_hash,
                "bytes_hash": expected_hash,
                "bytes_size": len(body_bytes),
                "fetch_time": fetch_utc.isoformat(),
            }
            self.__audit.validate_record(record)
            bytes_hash = store._put_llm_response(
                body_bytes,
                Provenance(
                    source_id=f"llm:{model_id}",
                    fetch_time=fetch_utc,
                    vendor_timestamp=fetch_utc,
                ),
                reader=reader,
                model_id=model_id,
                prompt_hash=prompt_hash,
                params_hash=params_hash,
            )
            if bytes_hash != expected_hash:
                raise RuntimeError("rawstore returned an unexpected bytes hash")
            self.__audit.append(record)
            return bytes_hash

        self.put_llm_response = put_llm_response


def _ensure_utc(ts: datetime) -> datetime:
    if not isinstance(ts, datetime):
        raise TypeError("fetch_time must be a datetime")
    if ts.tzinfo is None:
        raise ValueError("fetch_time must be timezone-aware")
    return ts.astimezone(timezone.utc)
