package io.rooted.verify.about

import android.content.Intent
import android.net.Uri
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.padding
import androidx.compose.material3.Button
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import io.rooted.verify.ui.RootedMint
import io.rooted.verify.ui.RootedTextDim

private const val SITE_URL = "https://rooted-web-phi.vercel.app"

@Composable
fun AboutScreen() {
    val context = LocalContext.current

    Column(
        modifier = Modifier
            .fillMaxSize()
            .padding(20.dp),
        verticalArrangement = Arrangement.spacedBy(16.dp),
    ) {
        Text("Rooted", style = MaterialTheme.typography.headlineSmall)
        Text(
            "Rooted recovers stripped C2PA provenance for AI generated media by matching an " +
                "invisible watermark or perceptual fingerprint against a transparency logged " +
                "registry. Every result on this phone comes from the live API, backed by " +
                "Backblaze B2 and a signed Merkle log.",
            style = MaterialTheme.typography.bodyMedium,
            color = RootedTextDim,
        )
        Button(onClick = {
            context.startActivity(Intent(Intent.ACTION_VIEW, Uri.parse(SITE_URL)))
        }) {
            Text("Open rooted-web-phi.vercel.app")
        }
        Text(
            "Provenance proves origin, not truth.",
            style = MaterialTheme.typography.titleMedium,
            fontWeight = FontWeight.SemiBold,
            color = RootedMint,
        )
    }
}
