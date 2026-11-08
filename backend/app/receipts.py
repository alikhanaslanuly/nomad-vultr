import json
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Receipt as ReceiptORM
from app.security import hmac_sign, sha256_hex
from app.config import settings


def canonical_json(obj) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


async def create_receipt(session: AsyncSession, job_id: str, manifest: dict) -> dict:
    prev = await session.execute(
        select(ReceiptORM).order_by(ReceiptORM.id.desc()).limit(1)
    )
    prev_row = prev.scalars().first()
    prev_hash = prev_row.chain_hash if prev_row else "0" * 64
    payload = prev_hash + canonical_json(manifest)
    chain_hash = sha256_hex(payload.encode())
    signature = hmac_sign(settings.RECEIPT_SIGNING_KEY, chain_hash.encode())
    row = ReceiptORM(job_id=job_id, manifest_json=manifest, chain_hash=chain_hash, signature=signature)
    session.add(row)
    await session.commit()
    await session.refresh(row)
    return {
        "receipt_id": row.id,
        "job_id": job_id,
        "manifest": manifest,
        "chain_hash": chain_hash,
        "signature": signature,
        "verify_result": None,
    }


def fingerprint(events: list[dict]) -> list[str]:
    """Stable fingerprint for Re-verify — ignores ts/pid/seq."""
    out = []
    for e in events:
        d = e.get("detail") or {}
        parts = [e.get("kind", ""), str(d.get("canary_id", "")), str(d.get("dest", "")),
                 str(d.get("path", "")), str(d.get("resource", ""))]
        out.append("|".join(parts))
    return out