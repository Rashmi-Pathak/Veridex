"""Generation step: Genblaze multi-provider, behind a Protocol with a deterministic fake for tests.

FakeGenerator is the network-free stand-in the pipeline tests use. GenblazeGenerator is the real
multi-provider generator (GMICloud primary, OpenAI cross-provider fallback) used when the genblaze
extra and provider keys are present. Asset bytes are read defensively: a file:// asset is bounded to
the temp dir the provider writes to, and an https asset is fetched over https only, refusing
internal addresses and redirects, with a size cap.

The https path resolves the host exactly once, validates every returned address, then pins the
connection to a validated IP literal (preserving the original Host header and the SNI/certificate
hostname). Pinning closes the SSRF time-of-check/time-of-use window: a DNS answer that flips between
the check and the fetch (rebinding, or a multi-record round-robin) cannot redirect the connection to
an internal address, because the address that was validated is the address that is connected.
"""

from __future__ import annotations

import hashlib
import io
import ipaddress
import logging
import socket
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol
from urllib.parse import ParseResult, unquote, urlparse
from urllib.request import url2pathname

import numpy as np
from PIL import Image

logger = logging.getLogger("veridex_worker.generator")


@dataclass
class GenerationResult:
    image: Image.Image
    image_bytes: bytes
    model: str
    provider: str


class Generator(Protocol):
    def generate(self, prompt: str) -> GenerationResult: ...


class FakeGenerator:
    """Deterministic, network-free generator: a prompt-seeded image. Same prompt, same image."""

    def __init__(self, model: str = "fake-image-1", provider: str = "fake") -> None:
        self._model = model
        self._provider = provider

    def generate(self, prompt: str) -> GenerationResult:
        seed = int.from_bytes(hashlib.sha256(prompt.encode()).digest()[:4], "big")
        arr = np.random.default_rng(seed).integers(0, 256, (256, 256, 3), dtype=np.uint8)
        image = Image.fromarray(arr).resize((64, 64)).resize((256, 256))
        buf = io.BytesIO()
        image.save(buf, "PNG")
        return GenerationResult(image, buf.getvalue(), self._model, self._provider)


_MAX_ASSET_BYTES = 50 * 1024 * 1024  # cap on a fetched/read genblaze asset
_ASSET_FETCH_TIMEOUT = 120.0


class AssetFetchError(ValueError):
    """A genblaze asset could not be safely fetched (bad scheme, the SSRF guard, the size cap).

    Subclasses ``ValueError`` for backward compatibility with callers that treat asset-validation
    failures as ``ValueError``. It is the precise type the cross-provider fallback catches, so a
    genuine asset/provider problem falls back to OpenAI while an unrelated programming error (a
    ``TypeError``, an attribute change, an image decode failure) propagates instead of being masked.
    """


def _validated_addresses(host: str, port: int) -> list[str]:
    """Resolve ``host`` once and return every resolved address as an IP literal.

    The whole answer is rejected if ANY address is internal (private, loopback, link-local,
    reserved, multicast, or unspecified), de-mapping IPv4-mapped IPv6 first, so a multi-record or
    round-robin answer cannot smuggle an internal address past the guard. The returned literals are
    what the caller pins the connection to, so the address validated here is the address connected.
    """
    try:
        infos = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    except OSError as exc:
        raise AssetFetchError(f"cannot resolve genblaze asset host {host!r}") from exc
    addresses: list[str] = []
    for info in infos:
        ip: ipaddress.IPv4Address | ipaddress.IPv6Address = ipaddress.ip_address(info[4][0])
        if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped is not None:
            ip = ip.ipv4_mapped
        if (
            ip.is_private
            or ip.is_loopback
            or ip.is_link_local
            or ip.is_reserved
            or ip.is_multicast
            or ip.is_unspecified
        ):
            raise AssetFetchError(f"refusing to fetch a genblaze asset from internal address {ip}")
        addresses.append(str(ip))
    if not addresses:
        raise AssetFetchError(f"cannot resolve genblaze asset host {host!r}")
    return addresses


def _asset_bytes(url: str) -> bytes:
    """Read a genblaze asset's bytes, failing closed on an untrusted URL.

    OpenAI assets are a local file:// the provider already downloaded (bounded to the temp dir it
    writes to); GMICloud assets are remote URLs fetched over https only, with the SSRF pin and a
    size cap. The asset URL comes from the provider response, so this is defense in depth rather
    than a user-facing input path.
    """
    parsed = urlparse(url)
    if parsed.scheme == "file":
        raw_path = parsed.path or parsed.netloc
        path = Path(url2pathname(unquote(raw_path))).resolve()
        tmp_root = Path(tempfile.gettempdir()).resolve()
        if not path.is_relative_to(tmp_root):
            raise AssetFetchError(f"refusing to read a genblaze asset outside the temp dir: {path}")
        data = path.read_bytes()
        if len(data) > _MAX_ASSET_BYTES:
            raise AssetFetchError("genblaze asset exceeds the size cap")
        return data
    if parsed.scheme != "https":
        raise AssetFetchError(f"unsupported genblaze asset URL scheme: {parsed.scheme!r}")
    return _https_asset_bytes(url, parsed)


def _https_asset_bytes(url: str, parsed: ParseResult) -> bytes:
    """Fetch an https asset, pinning the connection to a once-resolved, validated IP.

    follow_redirects stays off: following a redirect would re-resolve a fresh (unvalidated) host and
    bypass the guard. The original hostname is preserved as the Host header and as the SNI/cert
    hostname so virtual-host routing and TLS certificate verification still work against the IP.
    """
    import httpx

    host = parsed.hostname
    if not host:
        raise AssetFetchError("genblaze asset URL has no host")
    port = parsed.port or 443
    pinned_ip = _validated_addresses(host, port)[0]
    connect_url = httpx.URL(url).copy_with(host=pinned_ip)
    host_header = host if parsed.port is None else f"{host}:{parsed.port}"
    headers = {"Host": host_header}
    extensions = {"sni_hostname": host}

    chunks: list[bytes] = []
    total = 0
    with (
        httpx.Client(timeout=_ASSET_FETCH_TIMEOUT, follow_redirects=False) as client,
        client.stream("GET", connect_url, headers=headers, extensions=extensions) as resp,
    ):
        resp.raise_for_status()
        for chunk in resp.iter_bytes():
            total += len(chunk)
            if total > _MAX_ASSET_BYTES:
                raise AssetFetchError("genblaze asset exceeds the size cap")
            chunks.append(chunk)
    return b"".join(chunks)


def _fallback_exception_types() -> tuple[type[Exception], ...]:
    """Exception types that justify a cross-provider fallback (vs. a bug that must propagate).

    Provider, network, timeout, and asset-fetch failures fall back to OpenAI; an unexpected type
    (TypeError, attribute change, image decode failure) is not listed here and so propagates.
    genblaze raises GenblazeError subclasses (PipelineError on step failure, ProviderError,
    PipelineTimeoutError) from ``Pipeline.run(raise_on_failure=True)``; it is imported lazily
    because the genblaze extra is optional and absent from the default install.
    """
    import httpx

    types: list[type[Exception]] = [AssetFetchError, httpx.HTTPError]
    try:
        from genblaze_core import GenblazeError
    except ImportError:
        pass
    else:
        types.append(GenblazeError)
    return tuple(types)


class GenblazeGenerator:
    """Real Genblaze multi-provider image generation.

    GMICloud is the primary provider (Seedream / FLUX et al.) with within-provider
    ``fallback_models`` for model-level MODEL_ERROR retries; OpenAI (gpt-image / DALL-E) is the
    cross-provider backstop when GMICloud fails entirely. Returns the generated image bytes; the
    Rooted pipeline then watermarks, stores to B2, signs, and indexes the asset for recovery.

    Needs the ``genblaze`` extra (genblaze-core + genblaze-gmicloud + genblaze-openai) and provider
    keys. GMICloudImageProvider reads GMI_API_KEY by default, so the key is passed explicitly to
    avoid an env-name mismatch with Rooted's GMI_CLOUD_API_KEY.
    """

    def __init__(
        self,
        gmi_api_key: str,
        *,
        gmi_model: str,
        gmi_fallback_models: list[str] | None = None,
        openai_api_key: str | None = None,
        openai_model: str = "gpt-image-1",
        timeout: float = 180.0,
    ) -> None:
        self._gmi_api_key = gmi_api_key
        self._gmi_model = gmi_model
        self._gmi_fallback_models = gmi_fallback_models or []
        self._openai_api_key = openai_api_key
        self._openai_model = openai_model
        self._timeout = timeout

    def generate(self, prompt: str) -> GenerationResult:
        fallback_errors = _fallback_exception_types()
        try:
            return self._generate_gmi(prompt)
        except fallback_errors as exc:
            # A provider/network/timeout/asset failure falls back across providers; an unexpected
            # error (a bug, an attribute change, a decode failure) propagates rather than being
            # masked as "GMICloud failed" with a silent provider switch.
            if not self._openai_api_key:
                raise
            logger.warning("GMICloud generation failed (%s); falling back to OpenAI", exc)
            return self._generate_openai(prompt)

    def _generate_gmi(self, prompt: str) -> GenerationResult:
        from genblaze_core import Modality, Pipeline
        from genblaze_gmicloud import GMICloudImageProvider

        result = (
            Pipeline("rooted-gen")
            .step(
                GMICloudImageProvider(api_key=self._gmi_api_key),
                model=self._gmi_model,
                prompt=prompt,
                modality=Modality.IMAGE,
                fallback_models=self._gmi_fallback_models,
            )
            .run(raise_on_failure=True, timeout=self._timeout)
        )
        return self._to_result(result)

    def _generate_openai(self, prompt: str) -> GenerationResult:
        from genblaze_core import Modality, Pipeline
        from genblaze_openai import DalleProvider

        result = (
            Pipeline("rooted-gen-fallback")
            .step(
                DalleProvider(api_key=self._openai_api_key),
                model=self._openai_model,
                prompt=prompt,
                modality=Modality.IMAGE,
            )
            .run(raise_on_failure=True, timeout=self._timeout)
        )
        return self._to_result(result)

    @staticmethod
    def _to_result(result: object) -> GenerationResult:
        step = result.run.steps[0]  # type: ignore[attr-defined]
        data = _asset_bytes(step.assets[0].url)
        image = Image.open(io.BytesIO(data)).convert("RGB")
        return GenerationResult(
            image=image, image_bytes=data, model=step.model, provider=step.provider
        )
