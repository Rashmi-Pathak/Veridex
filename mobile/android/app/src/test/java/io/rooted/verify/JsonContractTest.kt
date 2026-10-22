package io.rooted.verify

import io.rooted.verify.api.ApiError
import io.rooted.verify.api.LogResponse
import io.rooted.verify.api.ManifestResponse
import io.rooted.verify.api.MatchesResponse
import io.rooted.verify.api.ProofResponse
import io.rooted.verify.api.ReceiptResponse
import io.rooted.verify.api.RootedClient
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

// Decoding-contract tests against REAL responses. Every fixture below was captured live from
// https://rooted-api-ubvc.onrender.com on 2026-07-01 via curl, byte for byte. If the API shape
// drifts, these tests are the first thing that should break.
class JsonContractTest {

    private val json = RootedClient.json

    // Captured live: POST /matches/byContent with the credentialed demo sample image.
    private val matchesFixture = """
        {"matches":[{"manifestId":"urn:c2pa:demo-0000-0000-0000-000000000001","similarityScore":100,"endpoint":null}]}
    """.trimIndent()

    // Captured live: GET /manifests/urn%3Ac2pa%3Ademo-0000-0000-0000-000000000001
    private val manifestFixture = """
        {"manifestId":"urn:c2pa:demo-0000-0000-0000-000000000001","assetSha256":"ad3c659392e336952bb63c5b940ed3b3a238432c62171f176f295b1c344bbc64","createdAt":"2026-06-27T00:00:00Z","systemProvenance":{"model":"seedream-5.0-lite","provider":"gmicloud-image","generator":"genblaze"},"personalProvenance":{},"softBindings":[{"alg":"com.adobe.trustmark.P","value":"DEMO","scope":"all"}]}
    """.trimIndent()

    // Captured live: GET /manifests/urn%3Ac2pa%3Ademo-0000-0000-0000-000000000001/receipts
    private val receiptFixture = """
        {"@context":{"c2pa":"https://c2pa.org/ns/","receipt":"https://c2pa.org/ns/manifest-receipt#"},"@type":"org.c2pa.manifest-receipt","repository":{"uri":"https://rooted-api-ubvc.onrender.com","manifestId":"urn:c2pa:demo-0000-0000-0000-000000000001"},"anchor":{"uri":"https://rooted-api-ubvc.onrender.com/transparency/proof/urn%3Ac2pa%3Ademo-0000-0000-0000-000000000001","parameters":{"epoch":15},"proof":{"alg":"sha256","manifestId":"urn:c2pa:demo-0000-0000-0000-000000000001","leafIndex":0,"leafHash":"1e58030da5d9dd029875e490768da7938032dd3394b5a4027f1d95917c7f0430","treeSize":15,"rootHash":"e4db22a65dbfd93ec3d477e4669c24e8ee5fdc6a4234377f723a4d4dfb0e9af7","proof":{"metadata":{"algorithm":"sha256","security":true,"size":15},"rule":[0,0,0,0,0],"subset":[],"path":["fba6e8b97011664ea6e172d7d408d0a4dbd4e78d3aaf8661fdbc972d25b006e6","c8e33ecf7da48185dadcb4dc938652f4d7f6100da31744383b08d3bdaf893e7d","3775fcc01d75fc186257517b1789fef4c33199bec39ff9dc3465f671577cae53","8507188474cce462922f4cf5d8347b26f5123426c70513f583ddc9948d1d6c4a","2039642e7525659ab9164fe05f8109efcf507728a92f99122ac1cb44761e1f61"]},"checkpoint":{"epoch":15,"treeSize":15,"rootHash":"e4db22a65dbfd93ec3d477e4669c24e8ee5fdc6a4234377f723a4d4dfb0e9af7","signedAt":"2026-07-02T02:26:17.848259+00:00","signatureB64":"cbj85N8Eyq64PTSApy/0HDnEBOAKS2MVJr2ff15sND3dRzQONQEwsqBbyN17Yl4tA1WsyyuzRaSoyojAmF/yBg=="},"publicKeyHex":"b1d184a5a5bc6de34de2eef791d15fffb0b585650fa20331ca61722e7321fe16","keySource":"configured","serverVerified":true}},"verified":true}
    """.trimIndent()

    // Captured live: GET /transparency/proof/urn%3Ac2pa%3Ademo-0000-0000-0000-000000000001
    private val proofFixture = """
        {"manifestId":"urn:c2pa:demo-0000-0000-0000-000000000001","leafIndex":0,"leafHash":"1e58030da5d9dd029875e490768da7938032dd3394b5a4027f1d95917c7f0430","treeSize":15,"rootHash":"e4db22a65dbfd93ec3d477e4669c24e8ee5fdc6a4234377f723a4d4dfb0e9af7","proof":{"metadata":{"algorithm":"sha256","security":true,"size":15},"rule":[0,0,0,0,0],"subset":[],"path":["fba6e8b97011664ea6e172d7d408d0a4dbd4e78d3aaf8661fdbc972d25b006e6","c8e33ecf7da48185dadcb4dc938652f4d7f6100da31744383b08d3bdaf893e7d","3775fcc01d75fc186257517b1789fef4c33199bec39ff9dc3465f671577cae53","8507188474cce462922f4cf5d8347b26f5123426c70513f583ddc9948d1d6c4a","2039642e7525659ab9164fe05f8109efcf507728a92f99122ac1cb44761e1f61"]},"checkpoint":{"epoch":15,"treeSize":15,"rootHash":"e4db22a65dbfd93ec3d477e4669c24e8ee5fdc6a4234377f723a4d4dfb0e9af7","signedAt":"2026-07-02T02:26:17.993470+00:00","signatureB64":"cbj85N8Eyq64PTSApy/0HDnEBOAKS2MVJr2ff15sND3dRzQONQEwsqBbyN17Yl4tA1WsyyuzRaSoyojAmF/yBg=="},"publicKeyHex":"b1d184a5a5bc6de34de2eef791d15fffb0b585650fa20331ca61722e7321fe16","keySource":"configured","serverVerified":true}
    """.trimIndent()

    // Captured live: GET /transparency/log (entries list abbreviated to the first three real
    // entries; treeSize and rootHash kept verbatim from the same capture).
    private val logFixture = """
        {"entries":[{"leafIndex":0,"manifestId":"urn:c2pa:demo-0000-0000-0000-000000000001","leafHash":"1e58030da5d9dd029875e490768da7938032dd3394b5a4027f1d95917c7f0430"},{"leafIndex":1,"manifestId":"urn:c2pa:demo-0000-0000-0000-0000-000000000002","leafHash":"5595c15f4bcfb080f5e42c4fe9b60e390660cdcd2750d3d491d4ab3e1a50e637"},{"leafIndex":2,"manifestId":"urn:c2pa:demo-0001-0000-0000-0000-000000000002","leafHash":"d3e1ffe72b9a1db8805dadd0a7e86c335591c10f240f9f625a93e48e9ae46255"}],"treeSize":15,"rootHash":"e4db22a65dbfd93ec3d477e4669c24e8ee5fdc6a4234377f723a4d4dfb0e9af7"}
    """.trimIndent()

    // Captured live: POST /matches/byContent with a non-image payload (HTTP 400 body).
    private val errorFixture = """
        {"detail":"invalid or unsupported image"}
    """.trimIndent()

    @Test
    fun decodesMatchesResponse() {
        val decoded = json.decodeFromString<MatchesResponse>(matchesFixture)
        assertEquals(1, decoded.matches.size)
        val match = decoded.matches.first()
        assertEquals("urn:c2pa:demo-0000-0000-0000-000000000001", match.manifestId)
        assertEquals(100.0, match.similarityScore!!, 0.0)
        assertNull(match.endpoint)
    }

    @Test
    fun decodesManifestResponse() {
        val decoded = json.decodeFromString<ManifestResponse>(manifestFixture)
        assertEquals("urn:c2pa:demo-0000-0000-0000-000000000001", decoded.manifestId)
        assertEquals(
            "ad3c659392e336952bb63c5b940ed3b3a238432c62171f176f295b1c344bbc64",
            decoded.assetSha256,
        )
        assertEquals("2026-06-27T00:00:00Z", decoded.createdAt)
        assertEquals("seedream-5.0-lite", decoded.systemProvenance?.model)
        assertEquals("gmicloud-image", decoded.systemProvenance?.provider)
        assertEquals("genblaze", decoded.systemProvenance?.generator)
        assertEquals(1, decoded.softBindings.size)
        assertEquals("com.adobe.trustmark.P", decoded.softBindings.first().alg)
    }

    @Test
    fun decodesReceiptResponseIncludingAtKeys() {
        val decoded = json.decodeFromString<ReceiptResponse>(receiptFixture)
        assertEquals("org.c2pa.manifest-receipt", decoded.type)
        assertNotNull(decoded.context)
        assertEquals(true, decoded.verified)
        assertEquals(
            "urn:c2pa:demo-0000-0000-0000-000000000001",
            decoded.repository?.manifestId,
        )
        val anchorProof = decoded.anchor?.proof
        assertNotNull(anchorProof)
        assertEquals(true, anchorProof?.serverVerified)
        assertEquals(15L, anchorProof?.treeSize)
        assertEquals(
            "e4db22a65dbfd93ec3d477e4669c24e8ee5fdc6a4234377f723a4d4dfb0e9af7",
            anchorProof?.rootHash,
        )
    }

    @Test
    fun decodesProofResponse() {
        val decoded = json.decodeFromString<ProofResponse>(proofFixture)
        assertEquals("urn:c2pa:demo-0000-0000-0000-000000000001", decoded.manifestId)
        assertEquals(0L, decoded.leafIndex)
        assertEquals(15L, decoded.treeSize)
        assertEquals(
            "e4db22a65dbfd93ec3d477e4669c24e8ee5fdc6a4234377f723a4d4dfb0e9af7",
            decoded.rootHash,
        )
        assertEquals(true, decoded.serverVerified)
        assertEquals(15L, decoded.checkpoint?.epoch)
        assertNotNull(decoded.checkpoint?.signatureB64)
        assertEquals("configured", decoded.keySource)
    }

    @Test
    fun decodesLogResponse() {
        val decoded = json.decodeFromString<LogResponse>(logFixture)
        assertEquals(3, decoded.entries.size)
        assertEquals(15L, decoded.treeSize)
        assertEquals(
            "e4db22a65dbfd93ec3d477e4669c24e8ee5fdc6a4234377f723a4d4dfb0e9af7",
            decoded.rootHash,
        )
        assertEquals(0L, decoded.entries.first().leafIndex)
        assertEquals("urn:c2pa:demo-0000-0000-0000-000000000001", decoded.entries.first().manifestId)
        assertTrue(decoded.entries.first().leafHash.startsWith("1e58030d"))
    }

    @Test
    fun decodesApiErrorDetail() {
        val decoded = json.decodeFromString<ApiError>(errorFixture)
        assertEquals("invalid or unsupported image", decoded.detail)
    }
}
