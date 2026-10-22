import XCTest
@testable import Rooted

// Decoding-contract tests against the live API's real JSON.
//
// Every fixture below is a byte-for-byte response captured with curl from the
// deployed service at https://veridex-api-ubvc.onrender.com on 2026-07-01.
// These are not mock data: they pin the decoding contract to what the live
// service actually returns, so a server-side field rename breaks these tests
// before it breaks the app.
final class ResponseDecodingTests: XCTestCase {
    // Captured live: POST /matches/byContent with the service's own demo
    // sample image (GET /demo/sample). Note the field name is
    // "similarityScore" on the wire.
    private let matchJSON = """
    {"matches":[{"manifestId":"urn:c2pa:demo-0000-0000-0000-000000000001","similarityScore":100,"endpoint":null}]}
    """

    // Captured live: POST /matches/byContent with a random noise image the
    // registry has never seen. Empty matches is the honest no-match shape.
    private let emptyMatchJSON = """
    {"matches":[]}
    """

    // Captured live: GET /manifests/urn%3Ac2pa%3Ademo-0000-0000-0000-000000000001
    private let manifestJSON = """
    {"manifestId":"urn:c2pa:demo-0000-0000-0000-000000000001","assetSha256":"ad3c659392e336952bb63c5b940ed3b3a238432c62171f176f295b1c344bbc64","createdAt":"2026-06-27T00:00:00Z","systemProvenance":{"model":"seedream-5.0-lite","provider":"gmicloud-image","generator":"genblaze"},"personalProvenance":{},"softBindings":[{"alg":"com.adobe.trustmark.P","value":"DEMO","scope":"all"}]}
    """

    // Captured live: GET /manifests/{id}/receipts (C2PA SBR 2.4 receipt with
    // JSON-LD style "@context" and "@type" keys).
    private let receiptJSON = """
    {"@context":{"c2pa":"https://c2pa.org/ns/","receipt":"https://c2pa.org/ns/manifest-receipt#"},"@type":"org.c2pa.manifest-receipt","repository":{"uri":"https://veridex-api-ubvc.onrender.com","manifestId":"urn:c2pa:demo-0000-0000-0000-000000000001"},"anchor":{"uri":"https://veridex-api-ubvc.onrender.com/transparency/proof/urn%3Ac2pa%3Ademo-0000-0000-0000-000000000001","parameters":{"epoch":15},"proof":{"alg":"sha256","manifestId":"urn:c2pa:demo-0000-0000-0000-000000000001","leafIndex":0,"leafHash":"1e58030da5d9dd029875e490768da7938032dd3394b5a4027f1d95917c7f0430","treeSize":15,"rootHash":"e4db22a65dbfd93ec3d477e4669c24e8ee5fdc6a4234377f723a4d4dfb0e9af7","proof":{"metadata":{"algorithm":"sha256","security":true,"size":15},"rule":[0,0,0,0,0],"subset":[],"path":["fba6e8b97011664ea6e172d7d408d0a4dbd4e78d3aaf8661fdbc972d25b006e6","c8e33ecf7da48185dadcb4dc938652f4d7f6100da31744383b08d3bdaf893e7d","3775fcc01d75fc186257517b1789fef4c33199bec39ff9dc3465f671577cae53","8507188474cce462922f4cf5d8347b26f5123426c70513f583ddc9948d1d6c4a","2039642e7525659ab9164fe05f8109efcf507728a92f99122ac1cb44761e1f61"]},"checkpoint":{"epoch":15,"treeSize":15,"rootHash":"e4db22a65dbfd93ec3d477e4669c24e8ee5fdc6a4234377f723a4d4dfb0e9af7","signedAt":"2026-07-02T02:24:09.046297+00:00","signatureB64":"cbj85N8Eyq64PTSApy/0HDnEBOAKS2MVJr2ff15sND3dRzQONQEwsqBbyN17Yl4tA1WsyyuzRaSoyojAmF/yBg=="},"publicKeyHex":"b1d184a5a5bc6de34de2eef791d15fffb0b585650fa20331ca61722e7321fe16","keySource":"configured","serverVerified":true}},"verified":true}
    """

    // Captured live: GET /transparency/proof/{id}
    private let proofJSON = """
    {"manifestId":"urn:c2pa:demo-0000-0000-0000-000000000001","leafIndex":0,"leafHash":"1e58030da5d9dd029875e490768da7938032dd3394b5a4027f1d95917c7f0430","treeSize":15,"rootHash":"e4db22a65dbfd93ec3d477e4669c24e8ee5fdc6a4234377f723a4d4dfb0e9af7","proof":{"metadata":{"algorithm":"sha256","security":true,"size":15},"rule":[0,0,0,0,0],"subset":[],"path":["fba6e8b97011664ea6e172d7d408d0a4dbd4e78d3aaf8661fdbc972d25b006e6","c8e33ecf7da48185dadcb4dc938652f4d7f6100da31744383b08d3bdaf893e7d","3775fcc01d75fc186257517b1789fef4c33199bec39ff9dc3465f671577cae53","8507188474cce462922f4cf5d8347b26f5123426c70513f583ddc9948d1d6c4a","2039642e7525659ab9164fe05f8109efcf507728a92f99122ac1cb44761e1f61"]},"checkpoint":{"epoch":15,"treeSize":15,"rootHash":"e4db22a65dbfd93ec3d477e4669c24e8ee5fdc6a4234377f723a4d4dfb0e9af7","signedAt":"2026-07-02T02:24:09.185089+00:00","signatureB64":"cbj85N8Eyq64PTSApy/0HDnEBOAKS2MVJr2ff15sND3dRzQONQEwsqBbyN17Yl4tA1WsyyuzRaSoyojAmF/yBg=="},"publicKeyHex":"b1d184a5a5bc6de34de2eef791d15fffb0b585650fa20331ca61722e7321fe16","keySource":"configured","serverVerified":true}
    """

    // Captured live: GET /transparency/log
    private let logJSON = """
    {"entries":[{"leafIndex":0,"manifestId":"urn:c2pa:demo-0000-0000-0000-000000000001","leafHash":"1e58030da5d9dd029875e490768da7938032dd3394b5a4027f1d95917c7f0430"},{"leafIndex":1,"manifestId":"urn:c2pa:demo-0000-0000-0000-0000-000000000002","leafHash":"5595c15f4bcfb080f5e42c4fe9b60e390660cdcd2750d3d491d4ab3e1a50e637"},{"leafIndex":2,"manifestId":"urn:c2pa:demo-0001-0000-0000-0000-000000000002","leafHash":"d3e1ffe72b9a1db8805dadd0a7e86c335591c10f240f9f625a93e48e9ae46255"},{"leafIndex":3,"manifestId":"urn:c2pa:demo-0002-0000-0000-0000-000000000002","leafHash":"35aebe0bcc4701680aaa2dcfdaf3ab2aadf8d225db9168623a61e795b6ab0db0"},{"leafIndex":4,"manifestId":"urn:c2pa:demo-0003-0000-0000-0000-000000000002","leafHash":"9f9408b255a518ad53ec519397a168ccb6c816ced9dd51284415cd19c993d0e6"},{"leafIndex":5,"manifestId":"urn:c2pa:demo-0004-0000-0000-0000-000000000002","leafHash":"f2806d8e15f4ff1c9b93ee8bb478422df9dc537a7664ed34a6971725dc573708"},{"leafIndex":6,"manifestId":"urn:c2pa:demo-0005-0000-0000-0000-000000000002","leafHash":"ba321ca45376e15440a23a60e9cfc5752225a7eab7799d780aae5280a67b4da0"},{"leafIndex":7,"manifestId":"urn:c2pa:demo-audio-0000-0000-0000-000000000001","leafHash":"3fed407925eb8d26bf793e323b90f9e9a83c62a02a3548174dae8d77b202c759"},{"leafIndex":8,"manifestId":"urn:c2pa:demo-video-0000-0000-0000-000000000001","leafHash":"320ed1a0b13700e93dfd6c17698ebb6885247f2f655d1ee69f86f86d4f04b4b4"},{"leafIndex":9,"manifestId":"urn:c2pa:demo-provider-nano-banana-000000000001","leafHash":"85c602b5243d63fb3ffbe82a24f2eedddded6c10bcd7631137c35189a355163c"},{"leafIndex":10,"manifestId":"urn:c2pa:demo-provider-flux-000000000001","leafHash":"9559a59842cf02938ff589f5c85e92423aa7a90a9bc48c5b47de2b39fd420157"},{"leafIndex":11,"manifestId":"urn:c2pa:demo-provider-qwen-000000000001","leafHash":"e1b7b883c4e31ca3154e138a2991952bb1c12353cbf7b9d9a79396e77995d178"},{"leafIndex":12,"manifestId":"urn:c2pa:b2-6e81a89d015a153dc4b40e2880374c597b8e7f97e00331bf47762de54f330de1","leafHash":"e224b091190bf107f340756f1557ce094a90ba6b746cfcae651368d762c58d34"},{"leafIndex":13,"manifestId":"urn:c2pa:b2-90d20f3043ba80e4dfa1db972fb2e9f927abb8be39611c08427c6a780909a086","leafHash":"f30607ba095f90289d3a45a5074dc5c37dbde9188989cb5be013b4e1497df0e9"},{"leafIndex":14,"manifestId":"urn:c2pa:b2-464b7ba1a2ea241e0e8ac4853833ca7e59f7ec6d4b81276f31386f3d47863f49","leafHash":"23e57276b275e3a224da392a5e613881d75903b69a17793c86e136657d225454"}],"treeSize":15,"rootHash":"e4db22a65dbfd93ec3d477e4669c24e8ee5fdc6a4234377f723a4d4dfb0e9af7"}
    """

    // Captured live: GET /status
    private let statusJSON = """
    {"service":"veridex-api","transparency":{"treeSize":15,"rootHash":"e4db22a65dbfd93ec3d477e4669c24e8ee5fdc6a4234377f723a4d4dfb0e9af7","checkpointEpoch":15,"keySource":"configured","publicKeyHex":"b1d184a5a5bc6de34de2eef791d15fffb0b585650fa20331ca61722e7321fe16"},"storage":{"backend":"backblaze-b2","bucket":"rooted-dev","demoAssetPresent":true},"recoveryIndex":"postgres+hnsw","algorithms":{"watermarks":["com.adobe.trustmark.P"],"fingerprints":[]},"generation":{"enabled":true,"configured":true,"perIpPerDay":5,"globalPerDay":50,"maxInFlight":2},"recoverySelfTest":{"recovered":true,"manifestId":"urn:c2pa:demo-0000-0000-0000-000000000001","similarityScore":100,"latencyMs":79}}
    """

    private func decode<T: Decodable>(_ type: T.Type, _ json: String) throws -> T {
        try JSONDecoder().decode(type, from: Data(json.utf8))
    }

    func testDecodesLiveMatchResponse() throws {
        let response = try decode(MatchResponse.self, matchJSON)
        XCTAssertEqual(response.matches.count, 1)
        XCTAssertEqual(response.matches.first?.manifestId, "urn:c2pa:demo-0000-0000-0000-000000000001")
        XCTAssertEqual(response.matches.first?.similarityScore, 100)
    }

    func testDecodesLiveEmptyMatchResponse() throws {
        let response = try decode(MatchResponse.self, emptyMatchJSON)
        XCTAssertTrue(response.matches.isEmpty)
    }

    func testDecodesLiveManifest() throws {
        let manifest = try decode(Manifest.self, manifestJSON)
        XCTAssertEqual(manifest.manifestId, "urn:c2pa:demo-0000-0000-0000-000000000001")
        XCTAssertEqual(manifest.assetSha256, "ad3c659392e336952bb63c5b940ed3b3a238432c62171f176f295b1c344bbc64")
        XCTAssertEqual(manifest.systemProvenance?.model, "seedream-5.0-lite")
        XCTAssertEqual(manifest.systemProvenance?.provider, "gmicloud-image")
        XCTAssertEqual(manifest.softBindings?.first?.alg, "com.adobe.trustmark.P")
    }

    func testDecodesLiveReceipt() throws {
        let receipt = try decode(Receipt.self, receiptJSON)
        XCTAssertEqual(receipt.type, "org.c2pa.manifest-receipt")
        XCTAssertEqual(receipt.context["c2pa"], "https://c2pa.org/ns/")
        XCTAssertEqual(receipt.repository.manifestId, "urn:c2pa:demo-0000-0000-0000-000000000001")
        XCTAssertEqual(receipt.anchor.parameters.epoch, 15)
        XCTAssertTrue(receipt.verified)
    }

    func testDecodesLiveProof() throws {
        let proof = try decode(TransparencyProof.self, proofJSON)
        XCTAssertEqual(proof.manifestId, "urn:c2pa:demo-0000-0000-0000-000000000001")
        XCTAssertEqual(proof.leafIndex, 0)
        XCTAssertEqual(proof.treeSize, 15)
        XCTAssertEqual(proof.rootHash, "e4db22a65dbfd93ec3d477e4669c24e8ee5fdc6a4234377f723a4d4dfb0e9af7")
        XCTAssertTrue(proof.serverVerified)
        XCTAssertEqual(proof.checkpoint?.epoch, 15)
    }

    func testDecodesLiveLog() throws {
        let log = try decode(TransparencyLog.self, logJSON)
        XCTAssertEqual(log.treeSize, 15)
        XCTAssertEqual(log.entries.count, 15)
        XCTAssertEqual(log.entries.first?.leafIndex, 0)
        XCTAssertEqual(log.entries.first?.manifestId, "urn:c2pa:demo-0000-0000-0000-000000000001")
        XCTAssertEqual(log.rootHash, "e4db22a65dbfd93ec3d477e4669c24e8ee5fdc6a4234377f723a4d4dfb0e9af7")
    }

    func testDecodesLiveStatus() throws {
        let status = try decode(ServiceStatus.self, statusJSON)
        XCTAssertEqual(status.service, "veridex-api")
        XCTAssertEqual(status.transparency.treeSize, 15)
    }

    func testManifestIdPercentEncoding() {
        XCTAssertEqual(
            RootedClient.encodeId("urn:c2pa:demo-0000-0000-0000-000000000001"),
            "urn%3Ac2pa%3Ademo-0000-0000-0000-000000000001"
        )
    }
}
