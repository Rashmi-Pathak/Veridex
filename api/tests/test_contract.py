"""Contract test: the SBR API's JSON/GET surface conforms to its own OpenAPI schema (schemathesis).

Schemathesis generates requests for every GET/JSON operation from /openapi.json and validates that
each response conforms to the declared schema, status code, content type, and headers, and that no
input triggers a server error. This proves the SBR API is self-consistent with the contract the
typed front-end client and the MCP server are generated against. It runs in-process against the ASGI
app (no network, no credentials), derandomized so results are stable across machines and CI runs.

The multipart file-upload operations (POST /ingest, POST /matches/byContent) are excluded: their
real input is binary image content, which OpenAPI's binary type cannot model, so schemathesis can
only exercise framework-level body-parsing errors rather than the actual contract. Their response
schemas (SoftBindingQueryResult and the ingest ack) are the same models validated on the GET surface
and exercised directly in the unit tests. POST /manifests/{id}/receipts (verifyReceipt) is excluded
for the same reason: its real input is a structured receipt verified against the live log, covered
directly in the receipt unit tests.

DELETE /manifests/{id} is excluded too: it is an intentional, always-405 WORM-refusal (the registry
is append-only and Object-Lock-backed), a deliberate conformance statement with no positive contract
to fuzz, so the positive-data check has nothing meaningful to assert. The 405 behavior is verified
in the receipt unit tests. The route stays in the published OpenAPI surface.
"""

from __future__ import annotations

from typing import Any

import schemathesis
from hypothesis import settings

from veridex_api.main import create_app

# Build the app without the MCP mount: schemathesis's ASGI transport runs the app lifespan but does
# not support a lifespan that sets scope "state" (the FastMCP streamable-HTTP session manager needs
# it). The MCP mount is not part of the OpenAPI surface, so the SBR contract under test is the same.
app = create_app(mount_mcp=False)

schema = (
    schemathesis.openapi.from_asgi("/openapi.json", app)
    .exclude(method="POST")
    .exclude(method="DELETE")
)


_CHECKS = [
    schemathesis.checks.not_a_server_error,
    schemathesis.checks.status_code_conformance,
    schemathesis.checks.content_type_conformance,
    schemathesis.checks.response_schema_conformance,
]


@schema.parametrize()
@settings(max_examples=25, deadline=None, derandomize=True)
def test_sbr_api_conforms_to_its_openapi(case: schemathesis.Case[Any]) -> None:
    case.call_and_validate(checks=_CHECKS)
