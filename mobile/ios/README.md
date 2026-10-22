# Veridex for iOS

The physical-world verifier for [Veridex](YOUR_VERIDEX_SITE_URL). Pick a photo or
point the camera at an image; the app uploads it to the live SBR API at
`YOUR_VERIDEX_API_URL`, which recovers the image's provenance via invisible
watermark or perceptual hash and returns the signed manifest with a live Merkle transparency
proof. A recovered result links straight to the shareable web receipt.

## Generate and run

The Xcode project is generated, never committed. From this directory:

```sh
brew install xcodegen
xcodegen generate
open Veridex.xcodeproj
```

Then select the `Veridex` scheme and run on an iOS 17+ simulator or device. The camera button
is disabled on simulators (no camera); the photo picker works everywhere.

## Share Extension

The app embeds a share extension named "Verify with Veridex". In any app that can share an
image (Photos, Safari, Files, a chat thread), tap Share on an image and pick Verify with
Veridex: the extension uploads that image to the same live API, then shows the recovered
manifest with its live Merkle transparency proof, or the honest no-match state. It compiles
the exact same client, downscaler, and view model files as the app's Verify tab, so there is
no second code path and no offline stub. The extension activates for exactly one shared image.

## Tests

Unit tests cover the hand-built multipart body, the image downscale helper, the share-payload
image picking, and the decoding contract. The decoding fixtures are byte-for-byte JSON
responses captured live from the deployed API with curl, so a server-side field rename fails
the suite before it breaks the app.

```sh
xcodebuild -project Veridex.xcodeproj -scheme Veridex \
  -destination 'platform=iOS Simulator,name=iPhone 16' \
  CODE_SIGNING_ALLOWED=NO build test
```

CI runs exactly this on every push and pull request that touches `mobile/ios/**`
(`.github/workflows/mobile-ios.yml`, macos-15 runner).

## Honesty note

Every screen renders live responses from the deployed API or an honest error state. There is
no mock data, no bundled sample result, and no offline stub. "No provenance found in the
registry for this image" is a real answer, not a failure. Provenance proves origin, not truth.

## TestFlight plan

One-liner: archive the `Veridex` scheme with a distribution certificate, upload via Xcode
Organizer to App Store Connect, and distribute through an internal TestFlight group so judges
can install without a paid device provisioning dance.

## Roadmap

- Phase M2 (done): the `RootedShare` share extension target, so any app's share sheet can
  send an image to Veridex for recovery.
