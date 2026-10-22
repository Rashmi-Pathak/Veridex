# /worker

Dramatiq actors running the provenance pipeline: Genblaze generation across providers (with
fallback_models), write asset + SHA-256 manifest to B2, TrustMark variant P watermark, PDQ compute
and index, then sign and append to the Merkle log. Redis broker.
