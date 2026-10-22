package io.rooted.verify.verify

import android.Manifest
import android.content.Intent
import android.content.pm.PackageManager
import android.net.Uri
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.PickVisualMediaRequest
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ColumnScope
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.Button
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.core.content.ContextCompat
import androidx.core.content.FileProvider
import coil.compose.AsyncImage
import io.rooted.verify.api.RootedClient
import io.rooted.verify.ui.RootedEmerald
import io.rooted.verify.ui.RootedTextDim
import io.rooted.verify.ui.RootedWarm
import io.rooted.verify.ui.middleTruncate
import java.io.File

private const val FILE_PROVIDER_AUTHORITY = "io.rooted.verify.fileprovider"

@Composable
fun VerifyScreen(viewModel: VerifyViewModel) {
    val context = LocalContext.current
    val state by viewModel.state.collectAsState()
    val previewUri by viewModel.previewUri.collectAsState()

    // The camera writes into a FileProvider uri in the app cache; keep the pending uri across
    // process death as a plain string.
    var pendingCameraUri by rememberSaveable { mutableStateOf<String?>(null) }

    val pickMedia = rememberLauncherForActivityResult(
        ActivityResultContracts.PickVisualMedia()
    ) { uri: Uri? ->
        if (uri != null) viewModel.verifyUri(context.contentResolver, uri)
    }

    val takePicture = rememberLauncherForActivityResult(
        ActivityResultContracts.TakePicture()
    ) { success ->
        val uri = pendingCameraUri?.let(Uri::parse)
        if (success && uri != null) viewModel.verifyUri(context.contentResolver, uri)
        pendingCameraUri = null
    }

    fun launchCamera() {
        val dir = File(context.cacheDir, "captures").apply { mkdirs() }
        val file = File(dir, "capture-${System.currentTimeMillis()}.jpg")
        val uri = FileProvider.getUriForFile(context, FILE_PROVIDER_AUTHORITY, file)
        pendingCameraUri = uri.toString()
        takePicture.launch(uri)
    }

    val requestCameraPermission = rememberLauncherForActivityResult(
        ActivityResultContracts.RequestPermission()
    ) { granted ->
        if (granted) launchCamera()
    }

    Column(
        modifier = Modifier
            .fillMaxSize()
            .verticalScroll(rememberScrollState())
            .padding(20.dp),
        verticalArrangement = Arrangement.spacedBy(16.dp),
    ) {
        Text("Verify an image", style = MaterialTheme.typography.headlineSmall)
        Text(
            "Pick, photograph, or share an image. Rooted matches it against the live " +
                "provenance registry by invisible watermark or perceptual fingerprint.",
            style = MaterialTheme.typography.bodyMedium,
            color = RootedTextDim,
        )

        Row(horizontalArrangement = Arrangement.spacedBy(12.dp)) {
            Button(onClick = {
                pickMedia.launch(
                    PickVisualMediaRequest(ActivityResultContracts.PickVisualMedia.ImageOnly)
                )
            }) {
                Text("Pick image")
            }
            OutlinedButton(onClick = {
                val granted = ContextCompat.checkSelfPermission(
                    context, Manifest.permission.CAMERA
                ) == PackageManager.PERMISSION_GRANTED
                if (granted) launchCamera()
                else requestCameraPermission.launch(Manifest.permission.CAMERA)
            }) {
                Text("Camera")
            }
        }

        Text(
            "Tip: from any app, Share an image to Rooted Verify and it lands here.",
            style = MaterialTheme.typography.bodySmall,
            color = RootedTextDim,
        )

        previewUri?.let { uri ->
            AsyncImage(
                model = uri,
                contentDescription = "Selected image",
                modifier = Modifier.fillMaxWidth(),
            )
        }

        when (val s = state) {
            is VerifyUiState.Idle -> {}

            is VerifyUiState.Uploading -> Row(
                verticalAlignment = Alignment.CenterVertically,
                horizontalArrangement = Arrangement.spacedBy(12.dp),
            ) {
                CircularProgressIndicator(modifier = Modifier.size(22.dp))
                Text("Uploading and matching against the live index...")
            }

            is VerifyUiState.NoMatch -> StatusCard(
                title = "NO MATCH",
                titleColor = RootedWarm,
            ) {
                Text(
                    "No provenance found. This image has no watermark or fingerprint match " +
                        "in the registry. Rooted only vouches for what it ingested.",
                    style = MaterialTheme.typography.bodyMedium,
                )
            }

            is VerifyUiState.Error -> StatusCard(
                title = "ERROR",
                titleColor = MaterialTheme.colorScheme.error,
            ) {
                Text(s.message, style = MaterialTheme.typography.bodyMedium)
                TextButton(onClick = { viewModel.reset() }) { Text("Dismiss") }
            }

            is VerifyUiState.Matched -> MatchedCard(s)
        }
    }
}

@Composable
private fun StatusCard(
    title: String,
    titleColor: androidx.compose.ui.graphics.Color,
    content: @Composable ColumnScope.() -> Unit,
) {
    Card(colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.surface)) {
        Column(
            modifier = Modifier.padding(16.dp),
            verticalArrangement = Arrangement.spacedBy(8.dp),
        ) {
            Text(
                title,
                style = MaterialTheme.typography.labelLarge,
                fontWeight = FontWeight.Bold,
                color = titleColor,
            )
            content()
        }
    }
}

@Composable
private fun MatchedCard(matched: VerifyUiState.Matched) {
    val context = LocalContext.current
    val serverVerified = matched.proof?.serverVerified == true

    Card(colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.surface)) {
        Column(
            modifier = Modifier.padding(16.dp),
            verticalArrangement = Arrangement.spacedBy(10.dp),
        ) {
            // The emerald badge is earned only by the live Merkle proof reporting
            // serverVerified true. A match without a verified proof says so plainly.
            if (serverVerified) {
                Badge(text = "VERIFIED", color = RootedEmerald)
            } else {
                Badge(text = "MATCHED, PROOF NOT VERIFIED", color = RootedWarm)
            }

            LabeledMono("Manifest", middleTruncate(matched.manifestId, 14))

            matched.manifest?.systemProvenance?.let { sp ->
                val modelLine = listOfNotNull(sp.model, sp.provider).joinToString(" / ")
                if (modelLine.isNotEmpty()) LabeledValue("Model", modelLine)
                sp.generator?.let { LabeledValue("Generator", it) }
            }
            matched.similarityScore?.let {
                LabeledValue("Similarity", trimNumber(it))
            }
            matched.proof?.let { proof ->
                if (proof.leafIndex != null && proof.treeSize != null) {
                    LabeledValue("Merkle proof", "leaf ${proof.leafIndex} of ${proof.treeSize}")
                }
                proof.rootHash?.let { LabeledMono("Root", middleTruncate(it, 12)) }
            }
            if (matched.receipt?.verified == true) {
                LabeledValue("C2PA 2.4 receipt", "verified")
            }

            // Honest partial failure lines.
            matched.manifestError?.let { PartialError("Manifest fetch failed: $it") }
            matched.proofError?.let { PartialError("Proof fetch failed: $it") }
            matched.receiptError?.let { PartialError("Receipt fetch failed: $it") }

            Spacer(Modifier.height(2.dp))
            Button(onClick = {
                val url = RootedClient.webReceiptUrl(matched.manifestId)
                context.startActivity(Intent(Intent.ACTION_VIEW, Uri.parse(url)))
            }) {
                Text("Open web receipt")
            }
        }
    }
}

@Composable
private fun Badge(text: String, color: androidx.compose.ui.graphics.Color) {
    Surface(color = color, shape = MaterialTheme.shapes.small) {
        Text(
            text,
            modifier = Modifier.padding(horizontal = 10.dp, vertical = 4.dp),
            style = MaterialTheme.typography.labelLarge,
            fontWeight = FontWeight.Bold,
            color = MaterialTheme.colorScheme.onPrimary,
        )
    }
}

@Composable
private fun LabeledValue(label: String, value: String) {
    Column {
        Text(label, style = MaterialTheme.typography.labelMedium, color = RootedTextDim)
        Text(value, style = MaterialTheme.typography.bodyMedium)
    }
}

@Composable
private fun LabeledMono(label: String, value: String) {
    Column {
        Text(label, style = MaterialTheme.typography.labelMedium, color = RootedTextDim)
        Text(value, style = MaterialTheme.typography.bodyMedium, fontFamily = FontFamily.Monospace)
    }
}

@Composable
private fun PartialError(message: String) {
    Text(
        message,
        style = MaterialTheme.typography.bodySmall,
        color = MaterialTheme.colorScheme.error,
    )
}

private fun trimNumber(value: Double): String =
    if (value == value.toLong().toDouble()) value.toLong().toString() else value.toString()
