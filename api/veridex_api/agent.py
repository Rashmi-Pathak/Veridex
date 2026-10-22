"""The live provenance agent: a Claude-powered conversational audit over Rooted's own tools.

POST /demo/agent answers a visitor's question by running a Claude tool-use loop whose tools are thin
wrappers over the live SBR API (the same surface Rooted's MCP server exposes). The agent can recover
the bundled demo asset through content matching, list the signed transparency-log leaves, recover a
signed manifest by id, and prove a manifest's inclusion under a signed checkpoint. The response
carries the agent's plain-language answer plus the exact trace of tool calls it made, so a judge
sees the agent reasoning over real provenance data, not a canned script.

The endpoint calls a paid model, so it is opt-in and hard-capped. It is enabled only when
ANTHROPIC_API_KEY is set; until then it returns an honest disabled response that still surfaces the
reachable MCP endpoint and suggested questions, so the panel is useful with no key. When enabled, a
per-IP daily cap, a global daily cap (a true ceiling on model spend: an attempt is never refunded),
an in-flight cap, a turn cap, and a small max_tokens bound the cost. Every model or tool error path
returns a labeled fallback, never a 500, so the demo panel cannot break during judging. The request
body is read with a hard size cap before any work, so a large unauthenticated request cannot exhaust
memory.
"""

from __future__ import annotations

import json
import logging
import os
import threading
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from urllib.parse import quote

import httpx
from fastapi import APIRouter, HTTPException, Request

from veridex_api.demo import DEMO_MANIFEST_ID, demo_sample_bytes
from veridex_api.generate import _client_ip  # the vetted X-Forwarded-For client-IP parse, reused
from veridex_provenance.models import CamelModel

logger = logging.getLogger(__name__)
router = APIRouter()

_QUESTION_MAX = 600
# The body is the question JSON only (no image upload), so 16 KiB is ample. Streamed and rejected at
# the cap before materialization, so a lying or absent Content-Length cannot exhaust memory.
_MAX_BODY_BYTES = 16 * 1024
_MAX_TOKENS = 1024
# The recent transparency leaves are trimmed to this many entries before they go to the model,
# so the tool result stays small regardless of how large the log grows.
_LOG_PREVIEW_LIMIT = 15

# A reachable MCP endpoint judges can connect their own agent to (this app mounts the MCP at /mcp).
_MCP_PATH = "/mcp"

_SUGGESTED_QUESTIONS = [
    "What has Rooted signed recently? Show me the transparency log.",
    "Verify the demo asset and tell me what model generated it.",
    f"Recover the manifest for {DEMO_MANIFEST_ID} and prove it is in the log.",
    "Is the transparency log tamper-evident? Explain how.",
]

_SYSTEM_PROMPT = (
    "You are the provenance assistant for Rooted, an open, vendor-neutral C2PA Soft Binding "
    "Resolution server that recovers stripped provenance for AI-generated media. Answer the "
    "visitor's question by calling Rooted's live tools, then explain what they returned in plain "
    "language. Tools: verify_demo_asset recovers the bundled demo asset through perceptual content "
    "matching (the core recover-from-a-stripped-asset capability) and reports the recovery method, "
    "the similarity score, and the disclosed system provenance; list_transparency_log returns the "
    "recent signed Merkle leaves and the current tree head; recover_manifest returns the signed, "
    "redacted provenance manifest for a manifest id (personal provenance such as the prompt is "
    "withheld by the redaction layer); prove_inclusion returns the inclusion proof for a manifest "
    "id, pinned to a signed checkpoint. Prefer calling a tool over guessing, and cite the concrete "
    "values the tools return: manifest ids, similarity scores, leaf indices, the root hash. Keep "
    "answers short and concrete. State this honestly when relevant: provenance proves origin, not "
    f"truth. A known starting handle is the demo manifest id {DEMO_MANIFEST_ID}."
)

_TOOLS: list[dict[str, Any]] = [
    {
        "name": "verify_demo_asset",
        "description": (
            "Recover the bundled demo asset (a real AI-generated image) through Rooted's "
            "perceptual content matching. Returns whether provenance was recovered, by which "
            "method, the similarity score, and the disclosed system provenance."
        ),
        "input_schema": {"type": "object", "properties": {}, "additionalProperties": False},
    },
    {
        "name": "list_transparency_log",
        "description": (
            "List the most recent signed leaves of Rooted's Merkle transparency log, plus the "
            "current tree size and root hash."
        ),
        "input_schema": {"type": "object", "properties": {}, "additionalProperties": False},
    },
    {
        "name": "recover_manifest",
        "description": (
            "Recover the signed, redacted provenance manifest for a manifest id. Personal "
            "provenance (such as the generation prompt) is withheld by the redaction layer."
        ),
        "input_schema": {
            "type": "object",
            "properties": {"manifest_id": {"type": "string"}},
            "required": ["manifest_id"],
            "additionalProperties": False,
        },
    },
    {
        "name": "prove_inclusion",
        "description": (
            "Return the inclusion proof for a manifest id in the transparency log, pinned to a "
            "signed checkpoint, so the leaf is bound to a signed tree head the caller can verify."
        ),
        "input_schema": {
            "type": "object",
            "properties": {"manifest_id": {"type": "string"}},
            "required": ["manifest_id"],
            "additionalProperties": False,
        },
    },
]

_GEMINI_TOOLS = [
    {
        "function_declarations": [
            {
                "name": "verify_demo_asset",
                "description": (
                    "Recover the bundled demo asset through Veridex's perceptual content matching. "
                    "Returns whether provenance was recovered, similarity score, and system provenance."
                ),
                "parameters": {"type": "object", "properties": {}},
            },
            {
                "name": "list_transparency_log",
                "description": (
                    "List the most recent signed leaves of Veridex's Merkle transparency log, plus "
                    "the current tree size and root hash."
                ),
                "parameters": {"type": "object", "properties": {}},
            },
            {
                "name": "recover_manifest",
                "description": (
                    "Recover the signed, redacted provenance manifest for a manifest id."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {"manifest_id": {"type": "string", "description": "The C2PA manifest URN"}},
                    "required": ["manifest_id"],
                },
            },
            {
                "name": "prove_inclusion",
                "description": (
                    "Return the inclusion proof for a manifest id in the transparency log."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {"manifest_id": {"type": "string", "description": "The C2PA manifest URN"}},
                    "required": ["manifest_id"],
                },
            },
        ]
    }
]


# --- the cost guard: in-memory daily + concurrency caps (single instance, in-process is truth) ---


@dataclass
class _Decision:
    ok: bool
    reason: str = ""  # "ip" | "global" | "busy" when not ok


class _AgentLimiter:
    """In-memory daily and concurrency caps for the paid agent endpoint, mirroring the generation
    limiter. The deploy is one Render instance, so an in-process counter is the whole truth. There
    is deliberately no refund: an acquired slot is a potential model spend (the model can bill
    before a later turn fails), so the global daily counter is a hard ceiling on model RUNS, never
    rolled back. acquire() checks and increments every counter under one lock, so the caps hold
    under concurrency.
    """

    def __init__(self, per_ip_per_day: int, global_per_day: int, max_in_flight: int) -> None:
        self._per_ip = per_ip_per_day
        self._global = global_per_day
        self._max_in_flight = max_in_flight
        self._lock = threading.Lock()
        self._day = ""
        self._ip_counts: dict[str, int] = {}
        self._global_count = 0
        self._in_flight = 0

    def _roll(self, day: str) -> None:
        if day != self._day:
            self._day = day
            self._ip_counts = {}
            self._global_count = 0
            # _in_flight is deliberately NOT reset: a run still in progress across midnight keeps
            # its slot until it releases, so the concurrency cap holds through the boundary.

    def acquire(self, ip: str, day: str) -> _Decision:
        with self._lock:
            self._roll(day)
            if self._in_flight >= self._max_in_flight:
                return _Decision(False, "busy")
            if self._global_count >= self._global:
                return _Decision(False, "global")
            if self._ip_counts.get(ip, 0) >= self._per_ip:
                return _Decision(False, "ip")
            self._ip_counts[ip] = self._ip_counts.get(ip, 0) + 1
            self._global_count += 1
            self._in_flight += 1
            return _Decision(True)

    def release(self) -> None:
        with self._lock:
            if self._in_flight > 0:
                self._in_flight -= 1


def _build_limiter() -> _AgentLimiter:
    # global_per_day caps RUNS; each run makes up to VERIDEX_AGENT_MAX_TURNS model calls, so the true
    # model-call ceiling is global_per_day * max_turns. Behind Render's proxy the per-IP cap is
    # coarse (the client IP comes from a spoofable X-Forwarded-For), so global_per_day is the hard
    # spend ceiling and is kept conservative.
    return _AgentLimiter(
        per_ip_per_day=int(os.environ.get("VERIDEX_AGENT_PER_IP_DAY", "10")),
        global_per_day=int(os.environ.get("VERIDEX_AGENT_GLOBAL_DAY", "100")),
        max_in_flight=int(os.environ.get("VERIDEX_AGENT_MAX_INFLIGHT", "3")),
    )


_limiter = _build_limiter()


def reset_limiter() -> None:
    """Rebuild the limiter from the environment. Tests use this to set caps between cases."""
    global _limiter
    _limiter = _build_limiter()


def _model() -> str:
    """The agent model. Defaults to gemini-flash-lite-latest or claude-opus-4-8."""
    if os.environ.get("ANTHROPIC_API_KEY"):
        return os.environ.get("VERIDEX_AGENT_MODEL", "claude-opus-4-8")
    return os.environ.get("VERIDEX_AGENT_MODEL", "gemini-flash-lite-latest")


def _max_turns() -> int:
    return int(os.environ.get("VERIDEX_AGENT_MAX_TURNS", "5"))


def _enabled() -> bool:
    """The agent is opt-in: enabled when Anthropic or Gemini key is configured."""
    return bool(os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("GEMINI_API_KEY"))


# --- the in-process tool executor (calls the live SBR routes on this app, no network) -------------


async def _execute_tool(
    name: str, args: dict[str, Any], client: httpx.AsyncClient
) -> dict[str, Any]:
    """Run one agent tool against the live SBR API in-process. Untrusted model-supplied args are
    validated here; any failure returns a structured error the model can read, never an exception
    that aborts the loop."""
    try:
        if name == "verify_demo_asset":
            return await _verify_demo_asset(client)
        if name == "list_transparency_log":
            return await _list_transparency_log(client)
        if name == "recover_manifest":
            mid = args.get("manifest_id")
            if not isinstance(mid, str) or not mid:
                return {"error": "manifest_id must be a non-empty string"}
            return await _recover_manifest(client, mid)
        if name == "prove_inclusion":
            mid = args.get("manifest_id")
            if not isinstance(mid, str) or not mid:
                return {"error": "manifest_id must be a non-empty string"}
            return await _prove_inclusion(client, mid)
        return {"error": f"unknown tool: {name}"}
    except httpx.HTTPError as exc:
        # An in-process route error is reported to the model as a tool error, not surfaced as a 500.
        logger.warning("agent tool %s failed: %s", name, exc)
        return {"error": "the tool call failed"}
    except Exception as exc:  # noqa: BLE001 - any other failure degrades to a readable tool error
        # A non-HTTP failure (e.g. a malformed body) is also fed back to the model as a tool error
        # rather than aborting the loop, so one bad tool result never collapses the whole run.
        logger.warning("agent tool %s errored: %s", name, exc)
        return {"error": "the tool call failed"}


async def _verify_demo_asset(client: httpx.AsyncClient) -> dict[str, Any]:
    r = await client.post(
        "/matches/byContent", files={"file": ("demo.jpg", demo_sample_bytes(), "image/jpeg")}
    )
    r.raise_for_status()
    matches = r.json().get("matches") or []
    if not matches:
        return {"recovered": False, "reason": "no soft-binding match"}
    match = matches[0]
    manifest = await _recover_manifest(client, match["manifestId"])
    score = match.get("similarityScore")
    return {
        "recovered": True,
        "manifestId": match["manifestId"],
        "recoveryMethod": "fingerprint" if score is not None else "watermark",
        "similarityScore": score,
        "systemProvenance": (manifest.get("manifest") or {}).get("systemProvenance", {}),
    }


async def _list_transparency_log(client: httpx.AsyncClient) -> dict[str, Any]:
    r = await client.get("/transparency/log")
    r.raise_for_status()
    body = r.json()
    entries = body.get("entries") or []
    # Trim to the most recent leaves so the tool result stays small as the log grows.
    recent = entries[-_LOG_PREVIEW_LIMIT:]
    return {
        "treeSize": body.get("treeSize"),
        "rootHash": body.get("rootHash"),
        "recentEntries": recent,
        "truncated": len(entries) > len(recent),
    }


async def _recover_manifest(client: httpx.AsyncClient, manifest_id: str) -> dict[str, Any]:
    # Percent-encode the model-supplied id so httpx cannot normalize dot-segments (e.g. "../") into
    # a different route; a crafted id then 404s here instead of redirecting the in-process GET.
    r = await client.get(f"/manifests/{quote(manifest_id, safe='')}")
    if r.status_code == 404:
        return {"recovered": False, "reason": "no manifest for that id"}
    r.raise_for_status()
    return {"recovered": True, "manifest": r.json()}


async def _prove_inclusion(client: httpx.AsyncClient, manifest_id: str) -> dict[str, Any]:
    # Percent-encode the model-supplied id (see _recover_manifest) so a crafted id cannot be
    # normalized into a different route.
    r = await client.get(f"/transparency/proof/{quote(manifest_id, safe='')}")
    if r.status_code == 404:
        return {"included": False, "manifestId": manifest_id}
    r.raise_for_status()
    proof = r.json()
    return {
        "included": True,
        "manifestId": manifest_id,
        "leafIndex": proof.get("leafIndex"),
        "treeSize": proof.get("treeSize"),
        "rootHash": proof.get("rootHash"),
        "serverVerified": proof.get("serverVerified"),
        "keySource": proof.get("keySource"),
    }


# --- request/response models ----------------------------------------------------------------------


async def _read_question(request: Request) -> str:
    """Read the JSON body with a hard streaming byte cap, then extract the question."""
    total = 0
    chunks: list[bytes] = []
    async for chunk in request.stream():
        total += len(chunk)
        if total > _MAX_BODY_BYTES:
            raise HTTPException(status_code=413, detail="request body too large")
        chunks.append(chunk)
    body = b"".join(chunks)
    try:
        payload = json.loads(body) if body else {}
    except (json.JSONDecodeError, ValueError) as exc:
        raise HTTPException(status_code=400, detail="invalid JSON body") from exc
    if not isinstance(payload, dict) or not isinstance(payload.get("question"), str):
        raise HTTPException(status_code=400, detail="question must be a string")
    return str(payload["question"])


class AgentToolCall(CamelModel):
    """One tool call the agent made, with the model's arguments and the tool's result, so the UI can
    show the agent's real reasoning trace over live provenance data."""

    tool: str
    input: dict[str, Any]
    result: dict[str, Any]


class AgentResponse(CamelModel):
    """The agent's answer and its tool-call trace, or an honest disabled response. enabled is false
    when no Anthropic key is configured; fellBack is true when an enabled run hit a model or tool
    error and returned a labeled message instead. mcpEndpoint is the reachable MCP path a judge can
    connect their own agent to."""

    enabled: bool
    answer: str
    tool_calls: list[AgentToolCall]
    model: str
    mcp_endpoint: str
    suggested_questions: list[str]
    fell_back: bool = False
    reason: str | None = None


def _disabled_response(reason: str) -> AgentResponse:
    return AgentResponse(
        enabled=False,
        answer="",
        tool_calls=[],
        model=_model(),
        mcp_endpoint=_MCP_PATH,
        suggested_questions=_SUGGESTED_QUESTIONS,
        fell_back=False,
        reason=reason,
    )


def _fell_back_response(reason: str) -> AgentResponse:
    return AgentResponse(
        enabled=True,
        answer="",
        tool_calls=[],
        model=_model(),
        mcp_endpoint=_MCP_PATH,
        suggested_questions=_SUGGESTED_QUESTIONS,
        fell_back=True,
        reason=reason,
    )


@router.post("/demo/agent", response_model=AgentResponse, include_in_schema=False)
async def demo_agent(request: Request) -> AgentResponse:
    """Answer a provenance question by running a Claude tool-use loop over Rooted's live tools.
    Opt-in (ANTHROPIC_API_KEY) and hard-capped (per-IP/day, global/day, in-flight, turns, tokens).
    Disabled and every error path return a labeled response, never a 500."""
    question = (await _read_question(request)).strip()
    if not question:
        raise HTTPException(status_code=400, detail="question must not be empty")
    if len(question) > _QUESTION_MAX:
        raise HTTPException(status_code=400, detail=f"question exceeds {_QUESTION_MAX} characters")

    gemini_key = os.environ.get("GEMINI_API_KEY")
    anthropic_key = os.environ.get("ANTHROPIC_API_KEY")

    if not anthropic_key and not gemini_key:
        return _disabled_response("the live agent is not enabled on this deploy (no model key)")

    day = datetime.now(UTC).date().isoformat()
    ip = _client_ip(request)
    decision = _limiter.acquire(ip, day)
    if not decision.ok:
        reason = {
            "busy": "the agent is busy; please try again shortly",
            "global": "the daily agent budget is reached; showing suggestions instead",
            "ip": "the per-visitor agent limit is reached; showing suggestions instead",
        }[decision.reason]
        return _fell_back_response(reason)

    try:
        transport = httpx.ASGITransport(app=request.app)
        async with httpx.AsyncClient(
            transport=transport, base_url="http://rooted-internal", timeout=30.0
        ) as sbr_client:
            if gemini_key and not anthropic_key:
                return await _run_gemini_agent(gemini_key, sbr_client, question)

            from anthropic import AsyncAnthropic
            anthropic_client = AsyncAnthropic(timeout=httpx.Timeout(45.0, connect=5.0))
            try:
                return await _run_agent(anthropic_client, sbr_client, question)
            finally:
                await anthropic_client.close()
    except Exception as exc:  # noqa: BLE001 - the demo panel must never 500; label and move on
        logger.warning("agent run failed: %s", exc)
        return _fell_back_response("the agent could not complete the request")
    finally:
        _limiter.release()


async def _run_agent(
    anthropic_client: Any, sbr_client: httpx.AsyncClient, question: str
) -> AgentResponse:
    """The manual tool-use loop: call the model, run any tool calls in-process, feed the results
    back, and stop when the model answers (or the turn cap is reached). Returns the final answer and
    the full tool-call trace."""
    import anthropic

    messages: list[dict[str, Any]] = [{"role": "user", "content": question}]
    trace: list[AgentToolCall] = []
    final_text = ""

    for _ in range(_max_turns()):
        try:
            response = await anthropic_client.messages.create(
                model=_model(),
                max_tokens=_MAX_TOKENS,
                system=_SYSTEM_PROMPT,
                tools=_TOOLS,
                messages=messages,
            )
        except (anthropic.APIError, anthropic.APIConnectionError) as exc:
            logger.warning("anthropic call failed: %s", exc)
            return _fell_back_response("the model is unavailable; please try again shortly")

        if response.stop_reason == "refusal":
            return _fell_back_response("the model declined to answer that question")

        final_text = "".join(b.text for b in response.content if b.type == "text") or final_text

        if response.stop_reason == "max_tokens":
            # The model hit the per-call token cap mid-answer. Mark the partial answer rather than
            # presenting a clipped sentence as complete (the honesty rule).
            final_text = (final_text + " [response truncated at the length limit]").strip()
            break
        if response.stop_reason != "tool_use":
            break

        messages.append({"role": "assistant", "content": response.content})
        results: list[dict[str, Any]] = []
        for block in response.content:
            if block.type != "tool_use":
                continue
            args = block.input if isinstance(block.input, dict) else {}
            result = await _execute_tool(block.name, args, sbr_client)
            trace.append(AgentToolCall(tool=block.name, input=args, result=result))
            results.append(
                {"type": "tool_result", "tool_use_id": block.id, "content": json.dumps(result)}
            )
        messages.append({"role": "user", "content": results})

    if not final_text.strip():
        # The loop ended (the turn cap was reached, or no turn emitted text) with no answer. Route
        # this into the labeled fallback rather than returning a blank answer reported as success.
        return _fell_back_response("the agent reached its step limit before answering")

    return AgentResponse(
        enabled=True,
        answer=final_text.strip(),
        tool_calls=trace,
        model=_model(),
        mcp_endpoint=_MCP_PATH,
        suggested_questions=_SUGGESTED_QUESTIONS,
        fell_back=False,
    )


async def _run_gemini_agent(
    api_key: str, sbr_client: httpx.AsyncClient, question: str
) -> AgentResponse:
    """Run provenance agent loop using Google Gemini API."""
    model_name = _model()
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model_name}:generateContent?key={api_key}"

    contents: list[dict[str, Any]] = [{"role": "user", "parts": [{"text": question}]}]
    trace: list[AgentToolCall] = []
    final_text = ""

    async with httpx.AsyncClient(timeout=30.0) as http_c:
        for _ in range(_max_turns()):
            payload = {
                "system_instruction": {"parts": [{"text": _SYSTEM_PROMPT}]},
                "contents": contents,
                "tools": _GEMINI_TOOLS,
            }
            resp = await http_c.post(url, json=payload)
            if resp.status_code != 200:
                logger.warning("Gemini API error %s: %s", resp.status_code, resp.text)
                return _fell_back_response("the agent model is temporarily busy; please try again shortly")

            data = resp.json()
            candidates = data.get("candidates") or []
            if not candidates:
                break
            cand = candidates[0]
            parts = (cand.get("content") or {}).get("parts") or []

            function_calls = [p for p in parts if "functionCall" in p]
            text_parts = [p.get("text", "") for p in parts if "text" in p]
            if text_parts:
                final_text = "".join(text_parts).strip()

            if not function_calls:
                break

            contents.append({"role": "model", "parts": parts})

            resp_parts: list[dict[str, Any]] = []
            for call_part in function_calls:
                fn = call_part["functionCall"]
                fn_name = fn.get("name", "")
                fn_args = fn.get("args") or {}
                tool_result = await _execute_tool(fn_name, fn_args, sbr_client)
                trace.append(AgentToolCall(tool=fn_name, input=fn_args, result=tool_result))
                resp_parts.append({
                    "functionResponse": {
                        "name": fn_name,
                        "response": {"result": tool_result},
                    }
                })

            contents.append({"role": "user", "parts": resp_parts})

    if not final_text.strip():
        return _fell_back_response("the agent reached its step limit before answering")

    return AgentResponse(
        enabled=True,
        answer=final_text.strip(),
        tool_calls=trace,
        model=model_name,
        mcp_endpoint=_MCP_PATH,
        suggested_questions=_SUGGESTED_QUESTIONS,
        fell_back=False,
    )
