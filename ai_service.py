import os
import json
from typing import AsyncIterator, List, Dict, Optional
from groq import AsyncGroq
import httpx
from dotenv import load_dotenv
from schemas import _normalize_confidence

def _normalize_analysis(result: dict) -> dict:
    """Fix up LLM output before it touches the DB."""
    if "confidence" in result:
        result["confidence"] = _normalize_confidence(result["confidence"])
    # also normalize per-turn confidence in transcript analysis
    for turn in result.get("per_turn", []):
        if "confidence" in turn:
            turn["confidence"] = _normalize_confidence(turn["confidence"])
    return result

load_dotenv()
GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")

client = AsyncGroq(
    api_key=GROQ_API_KEY,
    http_client=httpx.AsyncClient(
        timeout=httpx.Timeout(60.0, connect=10.0),
        # if you need proxies: use 'proxy=' (singular) in httpx >= 0.28
    ),
)
MODEL = os.getenv("MODEL","")

# Non-streaming analysis call — JSON mode
INTENT_SYSTEM_PROMPT = """You are a dialogue-analysis engine.
Return STRICT JSON ONLY:
{
  "intent": one of ["greeting","question","complaint","request_info","objection","confirmation","closing","small_talk","other"],
  "dialogue_stage": one of ["opening","needs_analysis","information_gathering","proposal","negotiation","resolution","closing","post_close"],
  "confidence": an INTEGER between 0 and 100 (NOT a fraction — use 95, never 0.95),
  "reasoning": one short sentence
}
No markdown, no prose."""

# Streaming reply prompt — plain text deltas
REPLY_SYSTEM_PROMPT = """You are a helpful, concise customer-service assistant.
Reply in 1-3 short sentences. Be friendly and move the dialogue forward."""

FLOW_SYSTEM_PROMPT = """You are a dialogue-flow analyzer.
Given a transcript, return STRICT JSON ONLY:
{
  "overall_flow": ["stage1","stage2",...],
  "per_turn": [
    {"role":"...","content":"...","intent":"...","dialogue_stage":"...","confidence":0,"reasoning":"..."}
  ]
}
Stages: opening, needs_analysis, information_gathering, proposal, negotiation, resolution, closing, post_close
Intents: greeting, question, complaint, request_info, objection, confirmation, closing, small_talk, other
Return ONLY JSON."""

async def analyze_message(content: str, history: Optional[List[Dict]] = None) -> dict:
    msgs = [{"role": "system", "content": INTENT_SYSTEM_PROMPT}] \
         + (history or []) + [{"role": "user", "content": content}]
    resp = await client.chat.completions.create(
        model=MODEL, messages=msgs, temperature=0.2,
        response_format={"type": "json_object"}, max_tokens=512,
    )
    try:
        result = json.loads(resp.choices[0].message.content)
        return _normalize_analysis(result)
    except json.JSONDecodeError:
        return {"error": "json_parse_failed", "raw": resp.choices[0].message.content}


async def analyze_transcript(messages: List[Dict]) -> dict:
    transcript = "\n".join(f"[{m['role']}] {m['content']}" for m in messages)
    resp = await client.chat.completions.create(
        model=MODEL,
        messages=[
            {"role": "system", "content": FLOW_SYSTEM_PROMPT},
            {"role": "user", "content": f"Transcript:\n{transcript}"},
        ],
        temperature=0.1,
        response_format={"type": "json_object"},
        max_tokens=2048,
    )
    try:
        result = json.loads(resp.choices[0].message.content)
        return _normalize_analysis(result)
    except json.JSONDecodeError:
        return {"error": "json_parse_failed", "raw": resp.choices[0].message.content}



async def stream_reply(content: str, history: List[Dict]) -> AsyncIterator[str]:
    """Stream assistant reply token-by-token. Yields plain-text deltas."""
    msgs = [{"role": "system", "content": REPLY_SYSTEM_PROMPT}] \
         + history + [{"role": "user", "content": content}]
    stream = await client.chat.completions.create(
        model=MODEL, messages=msgs, temperature=0.7,
        stream=True, max_tokens=2048,
    )
    async for chunk in stream:
        delta = chunk.choices[0].delta.content
        if delta:
            yield delta

