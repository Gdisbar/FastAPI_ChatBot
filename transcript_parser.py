import json
import re
from typing import List, Dict

ROLE_PATTERN = re.compile(
    r"^\s*(?:\[)?(user|human|assistant|bot|ai|system)(?:\])?\s*[:\-]\s*(.+)$",
    re.IGNORECASE,
)


def _normalize_role(r: str) -> str:
    r = r.lower()
    if r in ("user", "human"):
        return "user"
    if r in ("assistant", "bot", "ai"):
        return "assistant"
    return "system"


def parse_transcript_file(filename: str, text: str) -> List[Dict]:
    """Parse an uploaded transcript file into a list of {role, content} dicts.

    Supports:
      - JSON:  [{"role":"user","content":"..."}, ...]
      - Plain text / Markdown lines like:
            user: Hi
            assistant: Hello!
            [user]: I need help
            bot - Sure
      - Multi-line messages (continuation lines without a role prefix are appended
        to the previous message)
    """
    name = (filename or "").lower()
    if name.endswith(".json"):
        try:
            data = json.loads(text)
            if not isinstance(data, list):
                raise ValueError("JSON transcript must be a list")
            return [{"role": _normalize_role(m["role"]), "content": m["content"]}
                    for m in data]
        except (json.JSONDecodeError, KeyError, ValueError) as e:
            raise ValueError(f"Invalid JSON transcript: {e}")

    # Plain-text / Markdown parsing
    messages: List[Dict] = []
    current_role: str | None = None
    buffer: List[str] = []

    for line in text.splitlines():
        m = ROLE_PATTERN.match(line)
        if m:
            if current_role is not None and buffer:
                messages.append({
                    "role": _normalize_role(current_role),
                    "content": "\n".join(buffer).strip(),
                })
            current_role = m.group(1)
            buffer = [m.group(2)]
        else:
            if current_role is not None:
                buffer.append(line)
            # else: skip leading lines without a role

    if current_role is not None and buffer:
        messages.append({
            "role": _normalize_role(current_role),
            "content": "\n".join(buffer).strip(),
        })

    if not messages:
        raise ValueError("No role-prefixed messages found in transcript")
    return messages