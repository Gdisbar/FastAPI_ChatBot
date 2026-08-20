import time
import uuid
import json
import logging
from contextlib import asynccontextmanager
from typing import List

from fastapi import FastAPI, Depends, HTTPException, Request, Response, UploadFile, File
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

import schemas
import crud
import models
from database import engine, async_session, get_db, init_db
from ai_service import analyze_message, stream_reply, analyze_transcript
from transcript_parser import parse_transcript_file

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("chatbot")


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    logger.info("DB initialized")
    yield
    await engine.dispose()


app = FastAPI(
    title="AI Dialogue Cheatsheet API (async + streaming)",
    version="2.0.0",
    lifespan=lifespan,
)

# ---------- Middleware ----------
@app.middleware("http")
async def log_and_time(request: Request, call_next):
    rid = str(uuid.uuid4())[:8]
    start = time.time()
    logger.info(f"[{rid}] -> {request.method} {request.url.path}")
    try:
        response: Response = await call_next(request)
    except Exception as e:
        logger.exception(f"[{rid}] error: {e}")
        return JSONResponse(status_code=500, content={"detail": "internal_error", "request_id": rid})
    ms = (time.time() - start) * 1000
    response.headers["X-Request-ID"] = rid
    response.headers["X-Process-Time-ms"] = f"{ms:.2f}"
    logger.info(f"[{rid}] <- {response.status_code} in {ms:.2f}ms")
    return response

app.add_middleware(
    CORSMiddleware, allow_origins=["*"], allow_credentials=True,
    allow_methods=["*"], allow_headers=["*"],
)


# ---------- Health ----------
@app.get("/health")
async def health():
    return {"status": "ok"}


# ---------- SSE helpers ----------
def _sse(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data)}\n\n"


# ---------- Streaming chat ----------
async def _chat_stream_generator(session_id: str, content: str):
    """Yields SSE events:
       1. event: metadata  (intent + stage + reasoning) — before tokens
       2. event: token      (one per LLM delta)
       3. event: done       (final ids)
    IMPORTANT: session is opened/closed INSIDE the generator so it lives
    across the entire stream (Depends(get_db) would be torn down too early).
    """
    async with async_session() as db:
        # 1. Load history
        history_rows = await crud.get_session_history(db, session_id, limit=10)
        history = [{"role": r.role, "content": r.content} for r in history_rows]

        # 2. Non-streaming analysis call
        analysis = await analyze_message(content, history=history)
        if "error" in analysis:
            yield _sse("error", analysis)
            return

        # 3. Persist the user message with the analysis attached
        user_row = await crud.create_row(
            db, session_id=session_id, role="user", content=content,
            intent=analysis.get("intent"),
            dialogue_stage=analysis.get("dialogue_stage"),
            confidence=analysis.get("confidence"), raw=analysis,
        )

        # 4. Push metadata event so client knows intent/stage before reply streams
        yield _sse("metadata", {
            "intent": analysis.get("intent"),
            "dialogue_stage": analysis.get("dialogue_stage"),
            "confidence": analysis.get("confidence"),
            "reasoning": analysis.get("reasoning"),
            "user_message_id": user_row.id,
        })

        # 5. Stream the reply tokens and accumulate them
        collected: List[str] = []
        async for delta in stream_reply(content, history):
            collected.append(delta)
            yield _sse("token", {"token": delta})

        # 6. Persist the assistant message
        full_reply = "".join(collected)
        assistant_row = await crud.create_row(
            db, session_id=session_id, role="assistant",
            content=full_reply, raw=analysis,
        )

        # 7. Final event with row id
        yield _sse("done", {
            "assistant_message_id": assistant_row.id,
            "user_message_id": user_row.id,
            "intent": analysis.get("intent"),
            "dialogue_stage": analysis.get("dialogue_stage"),
        })


@app.post("/chat/stream")
async def chat_stream(msg: schemas.MessageIn):
    """Streaming chat. Returns text/event-stream (SSE)."""
    return StreamingResponse(
        _chat_stream_generator(msg.session_id, msg.content),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",   # disable proxy buffering (nginx)
            "Connection": "keep-alive",
        },
    )


# ---------- File-upload transcript analysis ----------
ALLOWED_CONTENT_TYPES = {
    "application/json",
    "text/plain",
    "text/markdown",
    "application/octet-stream",  # browsers sometimes send this for .txt
}
MAX_FILE_BYTES = 2 * 1024 * 1024  # 2 MB


@app.post("/analyze/file", response_model=schemas.TranscriptAnalysisOut)
async def analyze_file(file: UploadFile = File(...)):
    """Upload a transcript file (.json, .txt, .md) and get intent + dialogue flow."""
    # 1. Validate
    if file.content_type not in ALLOWED_CONTENT_TYPES:
        raise HTTPException(400, f"Unsupported content type: {file.content_type}")

    raw = await file.read()
    if len(raw) > MAX_FILE_BYTES:
        raise HTTPException(413, "File too large (max 2MB)")

    try:
        text = raw.decode("utf-8")
        messages = parse_transcript_file(file.filename or "", text)
    except UnicodeDecodeError:
        raise HTTPException(400, "File must be UTF-8 encoded text")
    except ValueError as e:
        raise HTTPException(400, str(e))

    if len(messages) < 2:
        raise HTTPException(400, "Need at least 2 messages in transcript")

    # 2. Call Groq to analyze the full transcript
    result = await analyze_transcript(messages)
    if "error" in result:
        raise HTTPException(502, f"LLM error: {result.get('raw','')}")

    # 3. Persist every analyzed turn
    session_id = f"upload-{str(uuid.uuid4())[:8]}"
    async with async_session() as db:
        for turn in result.get("per_turn", []):
            await crud.create_row(
                db, session_id=session_id,
                role=turn.get("role", "user"),
                content=turn.get("content", ""),
                intent=turn.get("intent"),
                dialogue_stage=turn.get("dialogue_stage"),
                confidence=turn.get("confidence"),
                raw=turn,
            )

    return schemas.TranscriptAnalysisOut(
        session_id=session_id,
        filename=file.filename,
        overall_flow=result.get("overall_flow", []),
        per_turn=result.get("per_turn", []),
    )


# ---------- CRUD routes (async, use Depends) ----------

@app.get("/conversations", response_model=List[schemas.MessageOut])
async def list_convs(skip: int = 0, limit: int = 50, db: AsyncSession = Depends(get_db)):
    return await crud.list_conversations(db, skip, limit)


@app.get("/conversations/{cid}", response_model=schemas.MessageOut)
async def get_conv(cid: int, db: AsyncSession = Depends(get_db)):
    row = await crud.get_conversation(db, cid)
    if not row:
        raise HTTPException(404, "Not found")
    return row


@app.get("/sessions/{session_id}/history", response_model=List[schemas.MessageOut])
async def session_history(session_id: str, db: AsyncSession = Depends(get_db)):
    return await crud.get_session_history(db, session_id)


@app.patch("/conversations/{cid}", response_model=schemas.MessageOut)
async def update_conv(cid: int, body: schemas.ConversationUpdate,
                      db: AsyncSession = Depends(get_db)):
    row = await crud.update_conversation(db, cid, body.model_dump(exclude_unset=True))
    if not row:
        raise HTTPException(404, "Not found")
    return row


@app.delete("/conversations/{cid}")
async def delete_conv(cid: int, db: AsyncSession = Depends(get_db)):
    if not await crud.delete_conversation(db, cid):
        raise HTTPException(404, "Not found")
    return {"deleted": cid}


@app.delete("/sessions/{session_id}")
async def delete_session(session_id: str, db: AsyncSession = Depends(get_db)):
    n = await crud.delete_session(db, session_id)
    return {"session_id": session_id, "deleted_count": n}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)