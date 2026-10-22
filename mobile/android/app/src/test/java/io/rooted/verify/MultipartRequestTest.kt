package io.rooted.verify

import io.rooted.verify.api.RootedClient
import okhttp3.MultipartBody
import okio.Buffer
import okio.ByteString.Companion.encodeUtf8
import okio.ByteString.Companion.toByteString
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

// The SBR spec expects the upload as a multipart form part named "file". These tests inspect the
// exact request OkHttp would send, with no network involved.
class MultipartRequestTest {

    private val client = RootedClient(baseUrl = "https://example.test")
    private val jpegMagic = byteArrayOf(0xFF.toByte(), 0xD8.toByte(), 0xFF.toByte(), 0xE0.toByte())

    @Test
    fun buildsPostToMatchesByContent() {
        val request = client.buildMatchRequest(jpegMagic, "stripped.jpg")
        assertEquals("POST", request.method)
        assertEquals("https://example.test/matches/byContent", request.url.toString())
    }

    @Test
    fun bodyIsMultipartFormWithFilePart() {
        val request = client.buildMatchRequest(jpegMagic, "stripped.jpg")
        val body = request.body
        assertTrue(body is MultipartBody)
        val contentType = (body as MultipartBody).contentType().toString()
        assertTrue(contentType.startsWith("multipart/form-data"))

        val buffer = Buffer()
        body.writeTo(buffer)
        val raw = buffer.readByteString()

        // Part headers are ASCII, so a byte-level search is exact.
        assertTrue(raw.indexOf("name=\"file\"".encodeUtf8()) >= 0)
        assertTrue(raw.indexOf("filename=\"stripped.jpg\"".encodeUtf8()) >= 0)
        assertTrue(raw.indexOf("Content-Type: image/jpeg".encodeUtf8()) >= 0)
        // The image bytes travel unmodified.
        assertTrue(raw.indexOf(jpegMagic.toByteString()) >= 0)
    }

    @Test
    fun manifestIdColonsArePercentEncodedInPaths() {
        val id = "urn:c2pa:demo-0000-0000-0000-000000000001"
        assertEquals(
            "urn%3Ac2pa%3Ademo-0000-0000-0000-000000000001",
            RootedClient.encodePathSegment(id),
        )
        val request = client.buildGetRequest(
            "manifests/${RootedClient.encodePathSegment(id)}/receipts"
        )
        assertEquals(
            "https://example.test/manifests/urn%3Ac2pa%3Ademo-0000-0000-0000-000000000001/receipts",
            request.url.toString(),
        )
    }

    @Test
    fun webReceiptUrlIsEncoded() {
        assertEquals(
            "https://rooted-web-phi.vercel.app/r/urn%3Ac2pa%3Ademo-0000-0000-0000-000000000001",
            RootedClient.webReceiptUrl("urn:c2pa:demo-0000-0000-0000-000000000001"),
        )
    }
}
