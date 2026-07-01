import Foundation
import AppKit

final class AppDelegate: NSObject, NSApplicationDelegate {
    func applicationDidFinishLaunching(_ notification: Notification) {
        guard let window = NSApplication.shared.windows.first else { return }
        
        let bundleURL = Bundle.main.bundleURL
        let isInstallerMode = !bundleURL.path.contains("/Applications/") && !bundleURL.path.contains("/geocentric/mac_app")
        
        if isInstallerMode {
            window.title = "Geocentric Installer"
            window.titlebarAppearsTransparent = true
            window.isMovableByWindowBackground = true
            window.styleMask.insert(.fullSizeContentView)
            window.setContentSize(NSSize(width: 440, height: 340))
            window.center()
        } else {
            window.title = "Geocentric"
            window.titlebarAppearsTransparent = true
            window.isMovableByWindowBackground = false
            window.styleMask.insert(.fullSizeContentView)
            window.minSize = NSSize(width: 1180, height: 760)
        }
    }

    func applicationWillTerminate(_ notification: Notification) {
        DesktopServer.shared.terminateServer()
        OllamaManager.shared.stopOwnedServer()
    }
}
