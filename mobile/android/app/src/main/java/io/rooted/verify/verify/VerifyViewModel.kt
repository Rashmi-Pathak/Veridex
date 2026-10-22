package io.rooted.verify.verify

import android.content.ContentResolver
import android.net.Uri
import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import io.rooted.verify.api.ManifestResponse
import io.rooted.verify.api.ProofResponse
import io.rooted.verify.api.ReceiptResponse
import io.rooted.verify.api.RootedApiException
import io.rooted.verify.api.RootedClient
import io.rooted.verify.util.ImageScaler
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext

// Every state below is driven by a live API response or a real failure. There is no mock path.
sealed interface VerifyUiState {
    data object Idle : VerifyUiState
    data object Uploading : VerifyUiState
    data object NoMatch : VerifyUiState
    data class Matched(
        val manifestId: String,
        val similarityScore: Double?,
        val manifest: ManifestResponse?,
        val proof: ProofResponse?,
        val receipt: ReceiptResponse?,
        // Partial failures are surfaced, not hidden.
        val manifestError: String? = null,
        val proofError: String? = null,
        val receiptError: String? = null,
    ) : VerifyUiState

    data class Error(val message: String) : VerifyUiState
}

class VerifyViewModel(
    private val client: RootedClient = RootedClient(),
) : ViewModel() {

    private val _state = MutableStateFlow<VerifyUiState>(VerifyUiState.Idle)
    val state: StateFlow<VerifyUiState> = _state.asStateFlow()

    private val _previewUri = MutableStateFlow<Uri?>(null)
    val previewUri: StateFlow<Uri?> = _previewUri.asStateFlow()

    // Entry point for the photo picker, the camera capture, and the share target.
    fun verifyUri(resolver: ContentResolver, uri: Uri) {
        _previewUri.value = uri
        _state.value = VerifyUiState.Uploading
        viewModelScope.launch {
            val bytes = withContext(Dispatchers.IO) {
                runCatching { ImageScaler.loadDownscaledJpeg(resolver, uri) }.getOrNull()
            }
            if (bytes == null) {
                _state.value = VerifyUiState.Error("Could not read that image.")
                return@launch
            }
            verifyBytes(bytes)
        }
    }

    private suspend fun verifyBytes(bytes: ByteArray) {
        val matches = try {
            client.matchByContent(bytes, "capture.jpg")
        } catch (e: RootedApiException) {
            _state.value = VerifyUiState.Error(e.message ?: "Request failed.")
            return
        } catch (e: Exception) {
            _state.value = VerifyUiState.Error(networkMessage(e))
            return
        }

        val top = matches.matches.firstOrNull()
        if (top == null) {
            _state.value = VerifyUiState.NoMatch
            return
        }

        // Fetch the full evidence for the top match. Each piece fails independently and honestly.
        val manifest = runCatching { client.manifest(top.manifestId) }
        val proof = runCatching { client.proof(top.manifestId) }
        val receipt = runCatching { client.receipt(top.manifestId) }

        _state.value = VerifyUiState.Matched(
            manifestId = top.manifestId,
            similarityScore = top.similarityScore,
            manifest = manifest.getOrNull(),
            proof = proof.getOrNull(),
            receipt = receipt.getOrNull(),
            manifestError = manifest.exceptionOrNull()?.let { errorMessage(it) },
            proofError = proof.exceptionOrNull()?.let { errorMessage(it) },
            receiptError = receipt.exceptionOrNull()?.let { errorMessage(it) },
        )
    }

    fun reset() {
        _state.value = VerifyUiState.Idle
        _previewUri.value = null
    }

    private fun errorMessage(e: Throwable): String = when (e) {
        is RootedApiException -> e.message ?: "Request failed."
        else -> networkMessage(e)
    }

    private fun networkMessage(e: Throwable): String =
        "Network error: ${e.message ?: e.javaClass.simpleName}. The live API was unreachable."
}
