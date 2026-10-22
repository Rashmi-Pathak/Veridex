package io.rooted.verify.api

import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import kotlinx.serialization.SerialName
import kotlinx.serialization.Serializable
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonElement
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.MultipartBody
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.RequestBody.Companion.toRequestBody
import java.io.IOException
import java.net.URLEncoder
import java.util.concurrent.TimeUnit

// Response models for the live Rooted SBR API. Field names mirror the API's camelCase JSON
// exactly (verified against live responses; see the JsonContractTest fixtures). Unknown keys are
// ignored so additive API changes do not break the app.

@Serializable
data class MatchItem(
    val manifestId: String,
    val similarityScore: Double? = null,
    val endpoint: String? = null,
)

@Serializable
data class MatchesResponse(
    val matches: List<MatchItem> = emptyList(),
)

@Serializable
data class SystemProvenance(
    val model: String? = null,
    val provider: String? = null,
    val generator: String? = null,
)

@Serializable
data class SoftBinding(
    val alg: String? = null,
    val value: String? = null,
    val scope: String? = null,
)

@Serializable
data class ManifestResponse(
    val manifestId: String,
    val assetSha256: String? = null,
    val createdAt: String? = null,
    val systemProvenance: SystemProvenance? = null,
    val personalProvenance: JsonElement? = null,
    val softBindings: List<SoftBinding> = emptyList(),
)

@Serializable
data class Checkpoint(
    val epoch: Long? = null,
    val treeSize: Long? = null,
    val rootHash: String? = null,
    val signedAt: String? = null,
    val signatureB64: String? = null,
)

@Serializable
data class ProofResponse(
    val manifestId: String? = null,
    val leafIndex: Long? = null,
    val leafHash: String? = null,
    val treeSize: Long? = null,
    val rootHash: String? = null,
    // The inner Merkle audit path; kept opaque because the app trusts serverVerified and links to
    // the web receipt for independent inspection.
    val proof: JsonElement? = null,
    val checkpoint: Checkpoint? = null,
    val publicKeyHex: String? = null,
    val keySource: String? = null,
    val serverVerified: Boolean? = null,
)

@Serializable
data class ReceiptRepository(
    val uri: String? = null,
    val manifestId: String? = null,
)

@Serializable
data class ReceiptAnchor(
    val uri: String? = null,
    val parameters: JsonElement? = null,
    val proof: ProofResponse? = null,
)

// C2PA SBR 2.4 proof-of-ingestion receipt. The "@context" and "@type" keys need explicit
// SerialName mapping because they are not valid Kotlin identifiers.
@Serializable
data class ReceiptResponse(
    @SerialName("@context") val context: JsonElement? = null,
    @SerialName("@type") val type: String? = null,
    val repository: ReceiptRepository? = null,
    val anchor: ReceiptAnchor? = null,
    val verified: Boolean? = null,
)

@Serializable
data class LogEntry(
    val leafIndex: Long,
    val manifestId: String,
    val leafHash: String,
)

@Serializable
data class LogResponse(
    val entries: List<LogEntry> = emptyList(),
    val treeSize: Long? = null,
    val rootHash: String? = null,
)

@Serializable
data class ApiError(
    val detail: String? = null,
)

class RootedApiException(val code: Int, val detail: String) :
    IOException("HTTP $code: $detail")

class RootedClient(
    private val baseUrl: String = DEFAULT_BASE_URL,
    private val http: OkHttpClient = defaultHttpClient(),
) {

    suspend fun matchByContent(bytes: ByteArray, filename: String): MatchesResponse =
        execute(buildMatchRequest(bytes, filename))

    suspend fun manifest(id: String): ManifestResponse =
        execute(buildGetRequest("manifests/${encodePathSegment(id)}"))

    suspend fun receipt(id: String): ReceiptResponse =
        execute(buildGetRequest("manifests/${encodePathSegment(id)}/receipts"))

    suspend fun proof(id: String): ProofResponse =
        execute(buildGetRequest("transparency/proof/${encodePathSegment(id)}"))

    suspend fun log(): LogResponse =
        execute(buildGetRequest("transparency/log"))

    // Internal so unit tests can inspect the multipart body without network access.
    internal fun buildMatchRequest(bytes: ByteArray, filename: String): Request {
        val body = MultipartBody.Builder()
            .setType(MultipartBody.FORM)
            .addFormDataPart("file", filename, bytes.toRequestBody(JPEG))
            .build()
        return Request.Builder()
            .url("$baseUrl/matches/byContent")
            .post(body)
            .build()
    }

    internal fun buildGetRequest(path: String): Request =
        Request.Builder().url("$baseUrl/$path").get().build()

    private suspend inline fun <reified T> execute(request: Request): T =
        withContext(Dispatchers.IO) {
            http.newCall(request).execute().use { response ->
                val text = response.body?.string().orEmpty()
                if (!response.isSuccessful) {
                    val detail = runCatching { json.decodeFromString<ApiError>(text).detail }
                        .getOrNull()
                    throw RootedApiException(response.code, detail ?: "request failed")
                }
                json.decodeFromString(text)
            }
        }

    companion object {
        const val DEFAULT_BASE_URL = "https://rooted-api-ubvc.onrender.com"
        const val WEB_RECEIPT_BASE_URL = "https://rooted-web-phi.vercel.app/r/"

        private val JPEG = "image/jpeg".toMediaType()

        val json: Json = Json { ignoreUnknownKeys = true }

        // Manifest ids are URNs with colons; the API expects them percent encoded in path
        // segments (urn%3Ac2pa%3A...). URLEncoder targets query strings, so fix the two spots
        // where its output differs from path encoding.
        fun encodePathSegment(id: String): String =
            URLEncoder.encode(id, Charsets.UTF_8.name())
                .replace("+", "%20")

        fun webReceiptUrl(id: String): String = WEB_RECEIPT_BASE_URL + encodePathSegment(id)

        private fun defaultHttpClient(): OkHttpClient = OkHttpClient.Builder()
            .connectTimeout(30, TimeUnit.SECONDS)
            .readTimeout(90, TimeUnit.SECONDS)
            .callTimeout(180, TimeUnit.SECONDS)
            .build()
    }
}
