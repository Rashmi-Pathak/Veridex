package io.rooted.verify.ui

import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.darkColorScheme
import androidx.compose.runtime.Composable
import androidx.compose.ui.graphics.Color

// Rooted brand palette, matching the web front end.
val RootedBackground = Color(0xFF060A09)
val RootedEmerald = Color(0xFF34D399)
val RootedMint = Color(0xFF5EFBD2)
val RootedWarm = Color(0xFFFFB86B)
val RootedSurface = Color(0xFF0C1512)
val RootedSurfaceHigh = Color(0xFF12201B)
val RootedText = Color(0xFFE6F4EE)
val RootedTextDim = Color(0xFF9DB8AC)

private val RootedColorScheme = darkColorScheme(
    primary = RootedEmerald,
    onPrimary = RootedBackground,
    secondary = RootedMint,
    onSecondary = RootedBackground,
    tertiary = RootedWarm,
    onTertiary = RootedBackground,
    background = RootedBackground,
    onBackground = RootedText,
    surface = RootedSurface,
    onSurface = RootedText,
    surfaceVariant = RootedSurfaceHigh,
    onSurfaceVariant = RootedTextDim,
    surfaceContainer = RootedSurface,
    surfaceContainerHigh = RootedSurfaceHigh,
    error = Color(0xFFFF6B6B),
    onError = RootedBackground,
    outline = Color(0xFF2A4038),
)

// Dark always: the app is a verification instrument, not a themed toy.
@Composable
fun RootedTheme(content: @Composable () -> Unit) {
    MaterialTheme(colorScheme = RootedColorScheme, content = content)
}

// Middle truncation for long ids and hashes so both ends stay recognizable.
fun middleTruncate(value: String, keep: Int = 10): String =
    if (value.length <= keep * 2 + 3) value
    else value.take(keep) + "..." + value.takeLast(keep)
