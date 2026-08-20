
**Running the server**
```bash
pip install -r requirements.txt
uvicorn main:app --reload
# Swagger at http://localhost:127.0.0.1:8000/docs
```

**Streaming chat (SSE)**

```bash
curl -N -X POST http://127.0.0.1:8000/chat/stream \
  -H "Content-Type: application/json" \
  -d '{"session_id":"s1","content":"Hey, my internet has been down for 2 hours!"}'
```
-N disables curl buffering. In JS, consume with fetch() + ReadableStream or EventSource.

**Upload File**

current as .txt but can be JSON - `sample_transcript.json`
```json
[
  {"role":"user","content":"Hi, I want to upgrade my plan."},
  {"role":"assistant","content":"Sure! May I know your current plan?"},
  {"role":"user","content":"I am on the Basic $20 plan."},
  {"role":"assistant","content":"We have Pro for $40 and Premium for $80."},
  {"role":"user","content":"$80 feels steep. Any discount?"},
  {"role":"assistant","content":"I can offer 10% off on Premium today."},
  {"role":"user","content":"Deal. Let us proceed."}
]
```

```bash
curl -X POST http://127.0.0.1:8000/analyze/file \
  -F "file=@sample_transcript.txt"
```

| Concern | Pattern | Why it matters |
|---|---|---|
| **Async driver** | `sqlite+aiosqlite://` + `create_async_engine` + `AsyncSession` | Non-blocking I/O under load |
| **Async ORM** | `Mapped`/`mapped_column` + `select()` + `await db.execute(...)` | SQLAlchemy 2.0 idiomatic |
| **Async Groq** | `AsyncGroq` + `await client.chat.completions.create(...)` | True concurrency with DB |
| **Streaming** | `stream=True` + `async for chunk in stream` → `StreamingResponse` | Token-by-token UX |
| **SSE wire format** | `event: X\ndata: {...}\n\n` | Standard, parseable in JS `EventSource` |
| **Session lifetime in stream** | Open `async with async_session()` **inside** the generator | `Depends(get_db)` would close mid-stream — common pitfall |
| **Two LLM calls per chat** | 1× non-streaming JSON for analysis → 1× streaming text for reply | Get structured metadata AND streamed reply |
| **File upload** | `UploadFile = File(...)` + `python-multipart` | No manual body parsing |
| **Transcript parser** | Supports JSON array *and* role-prefixed plain text/markdown | Robust to varied upload formats |
| **Lifespan init** | `@asynccontextmanager` + `await init_db()` | Replaces deprecated `@app.on_event("startup")` |
| **Stream-safe headers** | `Cache-Control: no-cache`, `X-Accel-Buffering: no` | Prevents nginx/reverse-proxy buffering killing SSE |

