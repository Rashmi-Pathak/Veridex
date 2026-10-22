import SwiftUI
import UIKit
import UniformTypeIdentifiers

// Principal view controller for the "Verify with Rooted" share extension.
// UIKit hosts the SwiftUI result view; the shared image is read from the
// extension context and handed to the same VerifyViewModel the app's Verify
// tab uses, so the extension talks to the live API through exactly the same
// code path. No mock data, no offline stub.
final class ShareViewController: UIViewController {
    private let viewModel = VerifyViewModel()

    override func viewDidLoad() {
        super.viewDidLoad()
        overrideUserInterfaceStyle = .dark
        // Matches RootedTheme.background so nothing flashes white while the
        // hosting controller attaches.
        view.backgroundColor = UIColor(red: 6.0 / 255.0, green: 10.0 / 255.0, blue: 9.0 / 255.0, alpha: 1.0)

        let host = UIHostingController(
            rootView: ShareResultView(viewModel: viewModel, onDone: { [weak self] in self?.finish() })
        )
        host.view.backgroundColor = .clear
        addChild(host)
        view.addSubview(host.view)
        host.view.translatesAutoresizingMaskIntoConstraints = false
        NSLayoutConstraint.activate([
            host.view.topAnchor.constraint(equalTo: view.topAnchor),
            host.view.bottomAnchor.constraint(equalTo: view.bottomAnchor),
            host.view.leadingAnchor.constraint(equalTo: view.leadingAnchor),
            host.view.trailingAnchor.constraint(equalTo: view.trailingAnchor),
        ])
        host.didMove(toParent: self)

        loadSharedImage()
    }

    // Reads the first image attachment from the share payload and runs the
    // live verification flow on it. A payload with no readable image is an
    // honest error state, not a crash.
    private func loadSharedImage() {
        let items = (extensionContext?.inputItems ?? []).compactMap { $0 as? NSExtensionItem }
        guard let provider = SharePayload.firstImageProvider(in: items) else {
            viewModel.fail("The shared item does not contain an image.")
            return
        }
        _ = provider.loadDataRepresentation(forTypeIdentifier: UTType.image.identifier) { [weak self] data, error in
            // The provider calls back on an arbitrary queue; hop to the main
            // actor before touching the view model.
            Task { @MainActor [weak self] in
                guard let self else { return }
                guard let data, let image = UIImage(data: data) else {
                    self.viewModel.fail(error?.localizedDescription ?? "Could not read the shared image.")
                    return
                }
                await self.viewModel.verify(image: image)
            }
        }
    }

    private func finish() {
        extensionContext?.completeRequest(returningItems: nil, completionHandler: nil)
    }
}
