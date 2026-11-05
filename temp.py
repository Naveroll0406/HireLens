"""
Check whether a Gemini API key actually works.

Finds the key in this order:
  1. the GEMINI_API_KEY / GOOGLE_API_KEY environment variable
  2. a .env file - path given as the first argument, else ./.env,
     else a .env sitting next to this script

Standard library only, so there is nothing to install.

Usage:
    python check_gemini_key.py
    python check_gemini_key.py "C:\\Users\\you\\project\\.env"

The key is never printed - only its length and where it was found.

Exit codes:  0 = key works   1 = key rejected   2 = not configured / network
"""

from __future__ import annotations

import json
import os
import re
import sys
import urllib.error
import urllib.request
from pathlib import Path

BASE = "https://generativelanguage.googleapis.com/v1beta"
NAMES = ("GEMINI_API_KEY", "GOOGLE_API_KEY")
TIMEOUT = 30


def parse_env_file(path: Path) -> dict[str, str]:
    """Read a .env file into a dict, tolerantly.

    Accepts the plain `NAME=value` form plus the things people actually paste
    into these files by mistake:
        export NAME=value          (bash)
        $env:NAME = "value"        (PowerShell)
        set NAME=value             (cmd)
    Surrounding quotes and stray whitespace are stripped.
    """
    values: dict[str, str] = {}
    try:
        text = path.read_text(encoding="utf-8-sig")
    except (OSError, UnicodeDecodeError):
        return values

    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        stripped = re.sub(r"^export\s+", "", stripped)
        stripped = re.sub(r"^\$env:", "", stripped)              # PowerShell
        stripped = re.sub(r"^set\s+", "", stripped, flags=re.I)  # cmd
        name, _, value = stripped.partition("=")
        name = name.strip()
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        if name:
            values[name] = value.strip()
    return values


def find_key() -> tuple[str | None, str]:
    """Return (key, where-it-came-from)."""
    for name in NAMES:
        raw = os.environ.get(name)
        if raw and raw.strip():
            return raw.strip().strip("\"'").strip(), f"environment variable {name}"

    candidates = []
    if len(sys.argv) > 1:
        candidates.append(Path(sys.argv[1]))
    candidates.append(Path.cwd() / ".env")
    candidates.append(Path(__file__).resolve().parent / ".env")

    for path in candidates:
        if not path.is_file():
            continue
        values = parse_env_file(path)
        for name in NAMES:
            if values.get(name):
                return values[name], f"{name} in {path}"
    return None, ""


def call(path: str, key: str, payload: dict | None = None) -> tuple[int, dict]:
    """GET/POST a Gemini endpoint, returning (status, parsed-body).

    The key goes in the x-goog-api-key header, not the query string: URLs end
    up in shell history and proxy logs, and a key there is a leaked key.
    """
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(f"{BASE}/{path}", data=data,
                                 method="POST" if data else "GET")
    req.add_header("x-goog-api-key", key)
    if data:
        req.add_header("Content-Type", "application/json")
    with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
        return resp.status, json.loads(resp.read().decode("utf-8") or "{}")


def explain(err: urllib.error.HTTPError) -> str:
    """Turn an HTTP error into something you can act on."""
    try:
        detail = json.loads(err.read().decode("utf-8")).get("error", {})
        message, status = detail.get("message", ""), detail.get("status", "")
    except (ValueError, AttributeError):
        message = status = ""
    hints = {
        400: "The key is malformed or not a Gemini key - check for stray "
             "quotes, spaces or a leading '$env:' pasted in with it.",
        401: "The key was not accepted at all.",
        403: "The key is real but not permitted: the Generative Language API "
             "may be disabled for its project, or the key has HTTP-referrer / "
             "IP restrictions that exclude this machine.",
        404: "Endpoint or model not found - the key may be fine.",
        429: "The key WORKS but you are rate-limited or out of free quota.",
    }
    line = f"HTTP {err.code}" + (f"  {status}" if status else "")
    if message:
        line += f"\n   API said: {message}"
    if hints.get(err.code):
        line += f"\n   Likely:   {hints[err.code]}"
    return line


def main() -> int:
    key, source = find_key()
    if not key:
        print("No key found.")
        print("Looked in: GEMINI_API_KEY / GOOGLE_API_KEY, ./.env, and a .env")
        print("next to this script.")
        print("\nA .env line must look like this - no '$env:', no quotes needed:")
        print("   GEMINI_API_KEY=your-key-here")
        return 2

    print(f"Found a key in {source}  ({len(key)} characters)")
    if " " in key or '"' in key or key.startswith("$"):
        print("   WARNING: that value contains a space, quote or '$'.")
        print("   It probably picked up shell syntax along with the key.")
    print("Checking it against Google ...\n")

    # --- Step 1: list models. Cheap, and it spends no generation quota.
    try:
        _, body = call("models", key)
    except urllib.error.HTTPError as err:
        print("KEY REJECTED")
        print(explain(err))
        return 1
    except urllib.error.URLError as err:
        print(f"Could not reach Google: {err.reason}")
        print("That is a network/proxy problem, not a verdict on the key.")
        return 2

    models = body.get("models", [])
    usable = [m for m in models
              if "generateContent" in (m.get("supportedGenerationMethods") or [])]
    print(f"KEY IS VALID - {len(models)} models visible, "
          f"{len(usable)} support generateContent.")
    for m in usable[:5]:
        print("   - " + m.get("name", "?").removeprefix("models/"))
    if len(usable) > 5:
        print(f"   ... and {len(usable) - 5} more")
    if not usable:
        print("\nThe key authenticates but no model accepts generateContent.")
        return 1

    # --- Step 2: smallest possible real generation, to prove it is usable.
    model = usable[0]["name"].removeprefix("models/")
    print(f"\nSending a 1-word test prompt to {model} ...")
    try:
        _, out = call(f"models/{model}:generateContent", key, {
            "contents": [{"parts": [{"text": "Reply with the single word: pong"}]}],
            # Gemini 2.5 models "think" before answering and spend output
            # tokens doing it, so a tiny budget returns MAX_TOKENS and no
            # text at all. Leave enough room for the thinking plus a word.
            "generationConfig": {"maxOutputTokens": 512},
        })
    except urllib.error.HTTPError as err:
        print("Listing worked but generating did not:")
        print(explain(err))
        return 1

    candidate = (out.get("candidates") or [{}])[0]
    parts = (candidate.get("content") or {}).get("parts") or []
    reply = next((p["text"].strip() for p in parts if p.get("text")), "")
    used = out.get("usageMetadata", {}).get("totalTokenCount", 0)

    if reply:
        print(f"Model replied: {reply!r}")
    else:
        # No text, but the call was authorised and billed - which is the
        # only thing this script is actually asserting.
        print(f"Model returned no text (finishReason="
              f"{candidate.get('finishReason', 'unknown')}), "
              f"but the request was accepted and billed {used} tokens.")
    print("\nThe key works end to end.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
