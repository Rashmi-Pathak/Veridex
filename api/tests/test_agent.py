"""Tests for the live provenance agent (/demo/agent).

The Anthropic client is faked, so no real model is called: the fake returns a scripted tool_use
turn followed by a final answer, and the test asserts the agent ran the tool against the LIVE SBR
routes in-process (real recovery, real transparency leaves) and returned the answer plus the tool
trace. Also covers the honest disabled response (no key), graceful fallbacks on a model error, a
refusal, and rate-limit exhaustion. Network-free: in-memory resolver/log, the demo seeded.
"""

from __future__ import annotations

from collections.abc import Iterator
from types import SimpleNamespace
from typing import Any, cast

import httpx
import pytest
from fastapi.testclient import TestClient

from veridex_api import agent, demo, generate, sbr
from veridex_api.main import app
from veridex_provenance.merkle import TransparencyLog
from veridex_provenance.resolver import InMemoryIndex, Resolver
from veridex_provenance.watermark import FakeWatermarker


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    sbr.set_resolver(Resolver(InMemoryIndex(), FakeWatermarker()))
    sbr.set_log(TransparencyLog())
    sbr.set_storage(None)
    generate.set_generator(None)
    # Predictable caps unless a test overrides them.
    for var in (
        "VERIDEX_AGENT_PER_IP_DAY",
        "VERIDEX_AGENT_GLOBAL_DAY",
        "VERIDEX_AGENT_MAX_INFLIGHT",
    ):
        monkeypatch.delenv(var, raising=False)
    agent.reset_limiter()
    demo.seed_demo(sbr.get_resolver(), sbr.get_log(), None)
    with TestClient(app) as c:
        yield c
    sbr.set_resolver(None)
    sbr.set_audio_resolver(None)
    sbr.set_video_resolver(None)
    sbr.set_log(None)
    sbr.set_storage(None)
    agent.reset_limiter()


# --- fake Anthropic client ------------------------------------------------------------------------


def _text(t: str) -> SimpleNamespace:
    return SimpleNamespace(type="text", text=t)


def _tool(name: str, tool_id: str, args: dict[str, Any]) -> SimpleNamespace:
    return SimpleNamespace(type="tool_use", id=tool_id, name=name, input=args)


def _resp(stop_reason: str, content: list[SimpleNamespace]) -> SimpleNamespace:
    return SimpleNamespace(stop_reason=stop_reason, content=content)


def _install_fake(monkeypatch: pytest.MonkeyPatch, responses: list[Any]) -> dict[str, Any]:
    holder: dict[str, Any] = {"closed": False}

    class _FakeMessages:
        def __init__(self) -> None:
            self.calls: list[dict[str, Any]] = []

        async def create(self, **kwargs: Any) -> Any:
            self.calls.append(kwargs)
            nxt = responses.pop(0)
            if isinstance(nxt, Exception):
                raise nxt
            return nxt

    class _FakeAnthropic:
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            self.messages = _FakeMessages()
            holder["client"] = self

        async def close(self) -> None:
            holder["closed"] = True

    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.setattr("anthropic.AsyncAnthropic", _FakeAnthropic)
    return holder


def _ask(client: TestClient, question: str) -> dict[str, Any]:
    r = client.post("/demo/agent", json={"question": question})
    assert r.status_code == 200, r.text
    return cast(dict[str, Any], r.json())


# --- disabled (no key) ----------------------------------------------------------------------------


def test_agent_disabled_without_key(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    body = _ask(client, "What has Rooted signed?")
    assert body["enabled"] is False
    assert body["mcpEndpoint"] == "/mcp"
    assert len(body["suggestedQuestions"]) >= 1
    assert body["toolCalls"] == []


# --- enabled tool-use loop against the live routes ------------------------------------------------


def test_agent_runs_list_transparency_log_tool(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    _install_fake(
        monkeypatch,
        [
            _resp("tool_use", [_tool("list_transparency_log", "t1", {})]),
            _resp("end_turn", [_text("Rooted has signed several assets.")]),
        ],
    )
    body = _ask(client, "What has Rooted signed recently?")
    assert body["enabled"] is True
    assert body["fellBack"] is False
    assert body["answer"] == "Rooted has signed several assets."
    assert len(body["toolCalls"]) == 1
    call = body["toolCalls"][0]
    assert call["tool"] == "list_transparency_log"
    # The tool ran against the live transparency log: it reports the real seeded tree size.
    assert call["result"]["treeSize"] >= demo.DEMO_ENTRY_COUNT


def test_agent_verifies_demo_asset_live(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    _install_fake(
        monkeypatch,
        [
            _resp("tool_use", [_tool("verify_demo_asset", "t1", {})]),
            _resp("end_turn", [_text("Recovered the demo asset.")]),
        ],
    )
    body = _ask(client, "Verify the demo asset.")
    result = body["toolCalls"][0]["result"]
    # A real recovery against the seeded demo asset: it self-matches with full similarity.
    assert result["recovered"] is True
    assert result["similarityScore"] == 100
    assert result["systemProvenance"]["model"] == "seedream-5.0-lite"


def test_agent_recover_manifest_validates_args(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    # An empty manifest_id is rejected by the tool, returning a structured error the model can read,
    # not an exception that aborts the loop.
    _install_fake(
        monkeypatch,
        [
            _resp("tool_use", [_tool("recover_manifest", "t1", {"manifest_id": ""})]),
            _resp("end_turn", [_text("I need a valid id.")]),
        ],
    )
    body = _ask(client, "Recover a manifest.")
    assert "error" in body["toolCalls"][0]["result"]


# --- graceful fallbacks ---------------------------------------------------------------------------


def test_agent_falls_back_on_model_error(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    import anthropic

    api_err = anthropic.APIConnectionError(
        message="down",
        request=httpx.Request("POST", "http://x"),
    )
    _install_fake(monkeypatch, [api_err])
    body = _ask(client, "anything")
    assert body["enabled"] is True
    assert body["fellBack"] is True
    assert body["answer"] == ""


def test_agent_falls_back_on_refusal(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    _install_fake(monkeypatch, [_resp("refusal", [])])
    body = _ask(client, "something disallowed")
    assert body["fellBack"] is True
    assert body["reason"] is not None


def test_agent_rate_limit_exhaustion_falls_back(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("VERIDEX_AGENT_GLOBAL_DAY", "0")
    agent.reset_limiter()
    _install_fake(monkeypatch, [_resp("end_turn", [_text("never reached")])])
    body = _ask(client, "What has Rooted signed?")
    assert body["enabled"] is True
    assert body["fellBack"] is True
    assert "budget" in (body["reason"] or "")


def test_agent_step_limit_falls_back(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    # The model keeps calling a tool and never emits a final answer. With a 1-turn cap the loop ends
    # with no text: it must return a labeled fallback, not a blank answer reported as success.
    monkeypatch.setenv("VERIDEX_AGENT_MAX_TURNS", "1")
    _install_fake(monkeypatch, [_resp("tool_use", [_tool("list_transparency_log", "t1", {})])])
    body = _ask(client, "loop forever please")
    assert body["enabled"] is True
    assert body["fellBack"] is True
    assert "step limit" in (body["reason"] or "")
    assert body["answer"] == ""


def test_agent_labels_truncated_answer(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    # A max_tokens stop returns a partial answer; it must be marked, not passed off as complete.
    _install_fake(monkeypatch, [_resp("max_tokens", [_text("a partial answer")])])
    body = _ask(client, "give me a long answer")
    assert body["fellBack"] is False
    assert body["answer"].endswith("[response truncated at the length limit]")


def test_agent_tool_error_degrades_to_readable_result(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    # A non-HTTP failure inside a tool is fed back to the model as a structured error, not raised
    # (which would abort the run). Force list_transparency_log to raise a ValueError.
    async def _boom(_client: object) -> dict[str, object]:
        raise ValueError("boom")

    monkeypatch.setattr(agent, "_list_transparency_log", _boom)
    _install_fake(
        monkeypatch,
        [
            _resp("tool_use", [_tool("list_transparency_log", "t1", {})]),
            _resp("end_turn", [_text("Handled the tool error.")]),
        ],
    )
    body = _ask(client, "list the log")
    assert body["enabled"] is True
    assert body["fellBack"] is False
    assert "error" in body["toolCalls"][0]["result"]


# --- input validation -----------------------------------------------------------------------------


def test_agent_rejects_empty_question(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    r = client.post("/demo/agent", json={"question": "   "})
    assert r.status_code == 400


def test_agent_rejects_oversized_question(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    r = client.post("/demo/agent", json={"question": "x" * 601})
    assert r.status_code == 400
