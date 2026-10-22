package io.rooted.verify

import android.content.Intent
import android.net.Uri
import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.activity.enableEdgeToEdge
import androidx.activity.viewModels
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.padding
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.List
import androidx.compose.material.icons.filled.CheckCircle
import androidx.compose.material.icons.filled.Info
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.NavigationBar
import androidx.compose.material3.NavigationBarItem
import androidx.compose.material3.NavigationBarItemDefaults
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.MutableIntState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.ui.Modifier
import androidx.core.content.IntentCompat
import io.rooted.verify.about.AboutScreen
import io.rooted.verify.log.LogScreen
import io.rooted.verify.log.LogViewModel
import io.rooted.verify.ui.RootedTextDim
import io.rooted.verify.ui.RootedTheme
import io.rooted.verify.verify.VerifyScreen
import io.rooted.verify.verify.VerifyViewModel

class MainActivity : ComponentActivity() {

    private val verifyViewModel: VerifyViewModel by viewModels()
    private val logViewModel: LogViewModel by viewModels()

    // Held at the activity level so an incoming share can switch to the Verify tab.
    private val selectedTab = mutableIntStateOf(0)

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        enableEdgeToEdge()
        setContent {
            RootedTheme {
                RootedApp(verifyViewModel, logViewModel, selectedTab)
            }
        }
        handleShareIntent(intent)
    }

    override fun onNewIntent(intent: Intent) {
        super.onNewIntent(intent)
        setIntent(intent)
        handleShareIntent(intent)
    }

    // The share target path: any app's share sheet -> Rooted Verify -> straight into the
    // live verify flow.
    private fun handleShareIntent(intent: Intent?) {
        if (intent?.action != Intent.ACTION_SEND) return
        if (intent.type?.startsWith("image/") != true) return
        val uri = IntentCompat.getParcelableExtra(intent, Intent.EXTRA_STREAM, Uri::class.java)
            ?: return
        // Consume the extra so a replayed intent does not re-upload the same image.
        intent.removeExtra(Intent.EXTRA_STREAM)
        selectedTab.intValue = 0
        verifyViewModel.verifyUri(contentResolver, uri)
    }
}

private data class Tab(val label: String, val icon: @Composable () -> Unit)

@Composable
private fun RootedApp(
    verifyViewModel: VerifyViewModel,
    logViewModel: LogViewModel,
    selectedTabState: MutableIntState,
) {
    val selectedTab by selectedTabState

    val tabs = listOf(
        Tab("Verify") { Icon(Icons.Filled.CheckCircle, contentDescription = null) },
        Tab("Log") { Icon(Icons.AutoMirrored.Filled.List, contentDescription = null) },
        Tab("About") { Icon(Icons.Filled.Info, contentDescription = null) },
    )

    Scaffold(
        containerColor = MaterialTheme.colorScheme.background,
        bottomBar = {
            NavigationBar(containerColor = MaterialTheme.colorScheme.surface) {
                tabs.forEachIndexed { index, tab ->
                    NavigationBarItem(
                        selected = selectedTab == index,
                        onClick = { selectedTabState.intValue = index },
                        icon = tab.icon,
                        label = { Text(tab.label) },
                        colors = NavigationBarItemDefaults.colors(
                            selectedIconColor = MaterialTheme.colorScheme.primary,
                            selectedTextColor = MaterialTheme.colorScheme.primary,
                            indicatorColor = MaterialTheme.colorScheme.surfaceVariant,
                            unselectedIconColor = RootedTextDim,
                            unselectedTextColor = RootedTextDim,
                        ),
                    )
                }
            }
        },
    ) { padding ->
        Box(
            modifier = Modifier
                .fillMaxSize()
                .padding(padding)
        ) {
            when (selectedTab) {
                0 -> VerifyScreen(verifyViewModel)
                1 -> LogScreen(logViewModel)
                else -> AboutScreen()
            }
        }
    }
}
