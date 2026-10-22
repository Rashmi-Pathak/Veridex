import { afterEach, describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import { AgentPanel } from "@/components/agent-panel";

// /api/demo/agent is a raw fetch (intentionally not in the typed schema, like /api/status), so it is
// stubbed on global fetch. Submit is user-driven, so each test types a question and clicks Submit.
function mockFetch(body: unknown, status = 200): void {
  globalThis.fetch = vi.fn(
    async () =>
      new Response(JSON.stringify(body), {
        status,
        headers: { "content-type": "application/json" },
      }),
  ) as unknown as typeof fetch;
}

const ENABLED = {
  enabled: true,
  answer: "Veridex has signed three assets in the last hour.",
  toolCalls: [{ tool: "list_recent_manifests", input: { limit: 3 }, result: { count: 3 } }],
  model: "claude-sonnet-4-5",
  mcpEndpoint: "/mcp",
  suggestedQuestions: ["What model signed the demo asset?"],
  fellBack: false,
  reason: null,
};

const DISABLED = {
  enabled: false,
  answer: "",
  toolCalls: [],
  model: "",
  mcpEndpoint: "/mcp",
  suggestedQuestions: ["What has Veridex signed recently?"],
  fellBack: false,
  reason: "No model key is configured on this deployment.",
};

const FELL_BACK = {
  enabled: true,
  answer: "",
  toolCalls: [],
  model: "claude-sonnet-4-5",
  mcpEndpoint: "/mcp",
  suggestedQuestions: [],
  fellBack: true,
  reason: "the daily agent budget is reached",
};

async function submitQuestion(text: string): Promise<void> {
  const user = userEvent.setup();
  await user.type(screen.getByPlaceholderText(/Ask about/i), text);
  await user.click(screen.getByText("Submit"));
}

afterEach(() => {
  vi.restoreAllMocks();
});

describe("AgentPanel", () => {
  it("renders the answer and the tool-call trace for an enabled response", async () => {
    mockFetch(ENABLED);
    render(<AgentPanel />);
    await submitQuestion("what has rooted signed lately");

    expect(await screen.findByText(/signed three assets in the last hour/)).toBeTruthy();
    expect(await screen.findByText("list_recent_manifests")).toBeTruthy();
    expect(screen.getByText(/answered by claude-sonnet-4-5/)).toBeTruthy();
  });

  it("surfaces the reason and the MCP endpoint when the agent is disabled", async () => {
    mockFetch(DISABLED);
    render(<AgentPanel />);
    await submitQuestion("anything");

    expect(await screen.findByText(/No model key is configured/)).toBeTruthy();
    expect(screen.getByText("/mcp")).toBeTruthy();
    // It must not fabricate an answer when the agent is off.
    expect(screen.queryByText(/answered by/)).toBeNull();
  });

  it("shows the fallback reason when the agent fell back", async () => {
    mockFetch(FELL_BACK);
    render(<AgentPanel />);
    await submitQuestion("verify the demo asset");

    expect(await screen.findByText(/daily agent budget is reached/)).toBeTruthy();
  });

  it("shows a backend-unreachable note on a non-OK status", async () => {
    mockFetch("", 500);
    render(<AgentPanel />);
    await submitQuestion("hello");

    expect(await screen.findByText(/Backend unreachable/)).toBeTruthy();
  });
});
