from typing import Optional, List
from sqlalchemy import select, delete
from sqlalchemy.ext.asyncio import AsyncSession
import models


async def create_row(db: AsyncSession, *, session_id: str, role: str, content: str,
                     intent: Optional[str] = None, dialogue_stage: Optional[str] = None,
                     confidence: Optional[int] = None, raw: Optional[dict] = None) -> models.Conversation:
    row = models.Conversation(
        session_id=session_id, role=role, content=content, intent=intent,
        dialogue_stage=dialogue_stage, confidence=confidence, raw_llm_response=raw,
    )
    db.add(row)
    await db.commit()
    await db.refresh(row)
    return row


async def get_conversation(db: AsyncSession, cid: int) -> Optional[models.Conversation]:
    res = await db.execute(select(models.Conversation).where(models.Conversation.id == cid))
    return res.scalar_one_or_none()


async def get_session_history(db: AsyncSession, session_id: str, limit: int = 20) -> List[models.Conversation]:
    res = await db.execute(
        select(models.Conversation)
        .where(models.Conversation.session_id == session_id)
        .order_by(models.Conversation.created_at.desc())
        .limit(limit)
    )
    return list(reversed(res.scalars().all()))  # chronological


async def list_conversations(db: AsyncSession, skip: int = 0, limit: int = 50) -> List[models.Conversation]:
    res = await db.execute(
        select(models.Conversation)
        .order_by(models.Conversation.created_at.desc())
        .offset(skip).limit(limit)
    )
    return list(res.scalars().all())


async def update_conversation(db: AsyncSession, cid: int, updates: dict) -> Optional[models.Conversation]:
    row = await get_conversation(db, cid)
    if not row:
        return None
    for k, v in updates.items():
        if hasattr(row, k) and v is not None:
            setattr(row, k, v)
    await db.commit()
    await db.refresh(row)
    return row


async def delete_conversation(db: AsyncSession, cid: int) -> bool:
    row = await get_conversation(db, cid)
    if not row:
        return False
    await db.delete(row)
    await db.commit()
    return True


async def delete_session(db: AsyncSession, session_id: str) -> int:
    res = await db.execute(
        delete(models.Conversation).where(models.Conversation.session_id == session_id)
    )
    await db.commit()
    return res.rowcount