# veridex-sbr

Recover stripped C2PA provenance for AI-generated media from your terminal.

`veridex-sbr` is the command-line client for [Veridex](https://github.com/StephenSook/veridex), an
open, vendor-neutral C2PA Soft Binding Resolution (SBR) server backed by Backblaze B2. When an image
loses its embedded C2PA manifest (after a screenshot or a re-encode), Veridex recovers the signed
provenance by matching an invisible watermark or a perceptual-hash fingerprint, and returns it with
a tamper-evident transparency-log proof.

The CLI talks to the same public SBR API the web client and the MCP server use. It defaults to the
live deploy; nothing is mocked, every command hits the real service.

## Install

```
pip install veridex-sbr
```

## Use

```
# recover the provenance of a (possibly stripped) image
veridex recover stripped.jpg

# fetch a recovered manifest by id (system provenance only; personal provenance withheld)
veridex manifest urn:c2pa:demo-0000-0000-0000-000000000001

# the transparency-log inclusion proof for a manifest
veridex proof urn:c2pa:demo-0000-0000-0000-000000000001

# the advertised soft-binding algorithms, and the live service status
veridex algorithms
veridex status
```

Point it at your own Veridex instance with `--api-url` or the `VERIDEX_API_URL` environment variable.

Provenance proves origin, not truth.

## License

Apache-2.0.
