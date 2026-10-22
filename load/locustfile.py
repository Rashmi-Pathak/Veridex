"""Demo-safety load smoke for the Rooted SBR read endpoints. Run before a demo or deploy:

    uv run uvicorn veridex_api.main:app --port 8000        # one shell
    uvx locust -f load/locustfile.py --host http://localhost:8000 --headless -u 20 -r 5 -t 15s

It hits the read endpoints (liveness, supportedAlgorithms, byBinding, a 404 manifest, the signed
checkpoint) AND the real recovery path the demo actually exercises: POST /matches/byContent, which
decodes the uploaded image and computes a PDQ hash (CPU-bound, offloaded to the threadpool) but
writes nothing. Watch the p95 latency and failure rate so the live demo will not fall over under
concurrent judges. locust is run via uvx so it is not a project dependency.
"""

from locust import HttpUser, between, task


class SbrReader(HttpUser):
    wait_time = between(0.1, 0.5)

    @task(3)
    def health(self) -> None:
        self.client.get("/health")

    @task(4)
    def matches_by_content(self) -> None:
        # The real recovery path a room of judges hits at once: fetch the demo asset, then POST it
        # to /matches/byContent (decode + PDQ). This is the CPU-bound path the GET tasks miss.
        sample = self.client.get("/demo/sample")
        if sample.status_code != 200:
            return
        self.client.post(
            "/matches/byContent",
            files={"file": ("sample.jpg", sample.content, "image/jpeg")},
        )

    @task(3)
    def supported_algorithms(self) -> None:
        self.client.get("/services/supportedAlgorithms")

    @task(5)
    def matches_by_binding(self) -> None:
        # The empty-match read path: a binding that resolves to no manifest exercises the resolver.
        self.client.get(
            "/matches/byBinding",
            params={"alg": "com.adobe.trustmark.P", "value": "RTNONE"},
        )

    @task(2)
    def checkpoint(self) -> None:
        self.client.get("/transparency/checkpoint")

    @task(1)
    def manifest_not_found(self) -> None:
        # 404 is the correct answer for an unknown manifest, so do not count it as a failure.
        with self.client.get("/manifests/urn:c2pa:none", catch_response=True) as r:
            if r.status_code == 404:
                r.success()
