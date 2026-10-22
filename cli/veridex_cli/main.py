"""Veridex SBR CLI: recover C2PA provenance for stripped media from your terminal.

Wraps the public Veridex Soft Binding Resolution API (the same spec endpoints the web client
and the MCP server use). Defaults to the live deploy; override with --api-url or the
VERIDEX_API_URL env var.

    pip install ./cli
    veridex recover stripped.jpg
"""

from __future__ import annotations

import json
import mimetypes
from pathlib import Path
from typing import Annotated, Any

import httpx
import typer

DEFAULT_API = "https://veridex-api-ubvc.onrender.com"

app = typer.Typer(
    help="Recover stripped C2PA provenance via the Veridex SBR API.",
    no_args_is_help=True,
    add_completion=False,
)

_state: dict[str, str] = {"api_url": DEFAULT_API}


@app.callback()
def _root(
    api_url: Annotated[
        str, typer.Option("--api-url", envvar="VERIDEX_API_URL", help="SBR API base URL")
    ] = DEFAULT_API,
) -> None:
    _state["api_url"] = api_url.rstrip("/")


def _client() -> httpx.Client:
    return httpx.Client(base_url=_state["api_url"], timeout=30.0)


def _print_json(label: str, data: Any) -> None:
    typer.echo(f"{label}: {json.dumps(data, indent=2)}")


@app.command()
def recover(
    image: Annotated[Path, typer.Argument(exists=True, dir_okay=False, readable=True)],
) -> None:
    """Recover the signed provenance manifest for a (possibly stripped) image, by fingerprint."""
    mime = mimetypes.guess_type(image.name)[0] or "image/jpeg"
    try:
        with _client() as c:
            r = c.post("/matches/byContent", files={"file": (image.name, image.read_bytes(), mime)})
            r.raise_for_status()
            matches = r.json().get("matches", [])
            if not matches:
                typer.secho("No provenance recovered: this asset is not in the registry.", fg="red")
                raise typer.Exit(1)
            match = matches[0]
            manifest_id = match["manifestId"]
            score = match.get("similarityScore")
            tail = f"  (similarity {score}/100)" if score is not None else ""
            typer.secho(f"RECOVERED  {manifest_id}{tail}", fg="green")
            details = c.get(f"/manifests/{manifest_id}")
            details.raise_for_status()
            body = details.json()
            provenance = body.get("systemProvenance", {})
            typer.echo(f"  created:   {body.get('createdAt')}")
            typer.echo(f"  model:     {provenance.get('model')}")
            typer.echo(f"  provider:  {provenance.get('provider')}")
            typer.echo(f"  generator: {provenance.get('generator')}")
    except httpx.HTTPError as exc:
        typer.secho(f"request failed: {exc}", fg="red")
        raise typer.Exit(2) from exc


@app.command()
def manifest(manifest_id: str) -> None:
    """Fetch a recovered manifest by id (system provenance only; personal provenance withheld)."""
    with _client() as c:
        r = c.get(f"/manifests/{manifest_id}")
        if r.status_code == 404:
            typer.secho("manifest not found", fg="red")
            raise typer.Exit(1)
        r.raise_for_status()
        _print_json("manifest", r.json())


@app.command()
def proof(manifest_id: str) -> None:
    """Fetch the transparency-log inclusion proof for a manifest."""
    with _client() as c:
        r = c.get(f"/transparency/proof/{manifest_id}")
        if r.status_code == 404:
            typer.secho("no proof for that manifest", fg="red")
            raise typer.Exit(1)
        r.raise_for_status()
        _print_json("proof", r.json())


@app.command()
def algorithms() -> None:
    """List the advertised soft-binding algorithms (the registered watermark; PDQ is internal)."""
    with _client() as c:
        r = c.get("/services/supportedAlgorithms")
        r.raise_for_status()
        _print_json("supportedAlgorithms", r.json())


@app.command()
def status() -> None:
    """Show the live SBR service status (recovery index, transparency tree, self-test)."""
    with _client() as c:
        r = c.get("/status")
        r.raise_for_status()
        body = r.json()
        tx = body.get("transparency", {})
        st = body.get("recoverySelfTest", {})
        typer.echo(f"recovery index: {body.get('recoveryIndex')}")
        typer.echo(f"transparency:   {tx.get('treeSize')} leaves, key {tx.get('keySource')}")
        typer.echo(f"self-test: recovered={st.get('recovered')} sim={st.get('similarityScore')}")


def main() -> None:
    app()


if __name__ == "__main__":
    main()
