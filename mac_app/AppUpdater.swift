import Foundation
import AppKit

final class AppUpdater: NSObject, ObservableObject, URLSessionDownloadDelegate {
    static let shared = AppUpdater()

    enum UpdateState: Equatable {
        case idle
        case checking
        case upToDate
        case updateAvailable(version: String, downloadURL: URL, releaseNotes: String?)
        case downloading(progress: Double)
        case installing
        case error(String)
        
        var label: String {
            switch self {
            case .idle: return "Check for updates"
            case .checking: return "Checking for updates..."
            case .upToDate: return "App is up to date"
            case .updateAvailable(let version, _, _): return "Update v\(version) available"
            case .downloading(let progress): return "Downloading (\(Int(progress * 100))%)"
            case .installing: return "Installing update..."
            case .error(let msg): return "Error: \(msg)"
            }
        }
    }

    @Published var state: UpdateState = .idle
    @Published var currentVersion: String = ""
    @Published var showUpdateBadge: Bool = false

    var isUpdating: Bool {
        switch state {
        case .downloading, .installing: return true
        default: return false
        }
    }

    private var downloadTask: URLSessionDownloadTask?
    private lazy var urlSession: URLSession = {
        let config = URLSessionConfiguration.default
        return URLSession(configuration: config, delegate: self, delegateQueue: nil)
    }()

    private override init() {
        super.init()
        self.currentVersion = Bundle.main.infoDictionary?["CFBundleShortVersionString"] as? String ?? "2.1.0"
        
        // Auto-check silently after startup
        DispatchQueue.global(qos: .background).asyncAfter(deadline: .now() + 2.0) { [weak self] in
            self?.checkForUpdates(silent: true)
        }
    }

    func checkForUpdates(silent: Bool = false) {
        if case .downloading = state { return }
        if case .installing = state { return }

        DispatchQueue.main.async {
            self.state = .checking
        }

        let url = URL(string: "https://api.github.com/repos/KiwiOnGit/geocentric/releases")!
        var request = URLRequest(url: url)
        request.timeoutInterval = 15
        request.setValue("GeocentricUpdater/1.0", forHTTPHeaderField: "User-Agent")

        URLSession.shared.dataTask(with: request) { [weak self] data, response, error in
            guard let self = self else { return }
            if let error = error {
                if !silent {
                    DispatchQueue.main.async {
                        self.state = .error("Failed to check for updates: \(error.localizedDescription)")
                    }
                } else {
                    DispatchQueue.main.async { self.state = .idle }
                }
                return
            }

            guard let data = data else {
                if !silent {
                    DispatchQueue.main.async {
                        self.state = .error("No data received from update server.")
                    }
                } else {
                    DispatchQueue.main.async { self.state = .idle }
                }
                return
            }

            do {
                struct Release: Decodable {
                    struct Asset: Decodable {
                        var name: String
                        var browser_download_url: URL
                    }
                    var tag_name: String
                    var body: String?
                    var assets: [Asset]
                }

                let releases = try JSONDecoder().decode([Release].self, from: data)
                guard let latestRelease = releases.first else {
                    DispatchQueue.main.async {
                        self.state = .upToDate
                        self.showUpdateBadge = false
                    }
                    return
                }

                var remoteVersion = latestRelease.tag_name
                if remoteVersion.lowercased().hasPrefix("v") {
                    remoteVersion.removeFirst()
                }

                if self.isVersion(remoteVersion, greaterThan: self.currentVersion) {
                    if let dmgAsset = latestRelease.assets.first(where: { self.isTrustedUpdateAsset(name: $0.name, url: $0.browser_download_url) }) {
                        DispatchQueue.main.async {
                            self.state = .updateAvailable(
                                version: remoteVersion,
                                downloadURL: dmgAsset.browser_download_url,
                                releaseNotes: latestRelease.body
                            )
                            self.showUpdateBadge = true
                        }
                    } else {
                        if !silent {
                            DispatchQueue.main.async {
                                self.state = .error("Update v\(remoteVersion) is available, but no .dmg was found in the release assets.")
                            }
                        } else {
                            DispatchQueue.main.async { self.state = .idle }
                        }
                    }
                } else {
                    DispatchQueue.main.async {
                        self.state = .upToDate
                        self.showUpdateBadge = false
                    }
                }
            } catch {
                if !silent {
                    DispatchQueue.main.async {
                        self.state = .error("Failed to parse update info: \(error.localizedDescription)")
                    }
                } else {
                    DispatchQueue.main.async { self.state = .idle }
                }
            }
        }.resume()
    }

    private func isVersion(_ v1: String, greaterThan v2: String) -> Bool {
        let parts1 = v1.split(separator: ".").compactMap { Int($0) }
        let parts2 = v2.split(separator: ".").compactMap { Int($0) }

        let count = max(parts1.count, parts2.count)
        for i in 0..<count {
            let p1 = i < parts1.count ? parts1[i] : 0
            let p2 = i < parts2.count ? parts2[i] : 0
            if p1 > p2 { return true }
            if p1 < p2 { return false }
        }
        return false
    }

    private func isTrustedUpdateAsset(name: String, url: URL) -> Bool {
        let lowerName = name.lowercased()
        return lowerName.hasSuffix(".dmg")
            && lowerName.contains("geocentric")
            && isAllowedUpdateURL(url)
    }

    private func isAllowedUpdateURL(_ url: URL) -> Bool {
        guard url.scheme?.lowercased() == "https",
              let host = url.host?.lowercased()
        else { return false }

        return host == "github.com"
            || host == "objects.githubusercontent.com"
            || host == "github-releases.githubusercontent.com"
    }

    func downloadAndInstallUpdate(from url: URL) {
        if case .downloading = state { return }
        if case .installing = state { return }
        guard isAllowedUpdateURL(url) else {
            DispatchQueue.main.async {
                self.state = .error("Update download URL is not trusted.")
            }
            return
        }

        DispatchQueue.main.async {
            self.state = .downloading(progress: 0)
        }

        downloadTask = urlSession.downloadTask(with: url)
        downloadTask?.resume()
    }

    func urlSession(_ session: URLSession, downloadTask: URLSessionDownloadTask, didWriteData bytesWritten: Int64, totalBytesWritten: Int64, totalBytesExpectedToWrite: Int64) {
        if totalBytesExpectedToWrite > 0 {
            let progress = Double(totalBytesWritten) / Double(totalBytesExpectedToWrite)
            DispatchQueue.main.async {
                self.state = .downloading(progress: progress)
            }
        }
    }

    func urlSession(_ session: URLSession, downloadTask: URLSessionDownloadTask, didFinishDownloadingTo location: URL) {
        let fm = FileManager.default
        let tempDir = fm.temporaryDirectory
        let dmgURL = tempDir.appendingPathComponent("GeocentricUpdate.dmg")

        do {
            try? fm.removeItem(at: dmgURL)
            try fm.moveItem(at: location, to: dmgURL)

            DispatchQueue.main.async {
                self.state = .installing
            }

            try self.mountAndInstall(dmgURL: dmgURL)
        } catch {
            DispatchQueue.main.async {
                self.state = .error("Failed to prepare update: \(error.localizedDescription)")
            }
        }
    }

    func urlSession(_ session: URLSession, task: URLSessionTask, didCompleteWithError error: Error?) {
        if let error = error {
            DispatchQueue.main.async {
                self.state = .error("Download failed: \(error.localizedDescription)")
            }
        }
    }

    private func mountAndInstall(dmgURL: URL) throws {
        let fm = FileManager.default
        let mountPoint = "/tmp/GeocentricUpdateMount"

        let _ = try? ProcessRunner.run(executable: "/usr/bin/hdiutil", arguments: ["detach", mountPoint, "-force"], currentDirectory: URL(fileURLWithPath: "/tmp"))

        let mountResult = try ProcessRunner.run(
            executable: "/usr/bin/hdiutil",
            arguments: ["attach", dmgURL.path, "-mountpoint", mountPoint, "-nobrowse", "-readonly"],
            currentDirectory: URL(fileURLWithPath: "/tmp")
        )

        guard mountResult.status == 0 else {
            throw NSError(domain: "AppUpdater", code: 2, userInfo: [NSLocalizedDescriptionKey: "Failed to mount DMG: \(mountResult.output)"])
        }

        let sourceAppURL = URL(fileURLWithPath: "\(mountPoint)/Geocentric.app")
        guard fm.fileExists(atPath: sourceAppURL.path) else {
            let _ = try? ProcessRunner.run(executable: "/usr/bin/hdiutil", arguments: ["detach", mountPoint, "-force"], currentDirectory: URL(fileURLWithPath: "/tmp"))
            throw NSError(domain: "AppUpdater", code: 3, userInfo: [NSLocalizedDescriptionKey: "Geocentric.app not found in mounted DMG."])
        }
        try validateMountedApp(sourceAppURL)

        let currentAppURL = Bundle.main.bundleURL
        let currentPath = shellQuoted(currentAppURL.path)
        let sourcePath = shellQuoted(sourceAppURL.path)
        let mountPath = shellQuoted(mountPoint)
        let dmgPath = shellQuoted(dmgURL.path)

        let scriptContent = """
        #!/bin/bash
        for i in {1..50}; do
            if ! kill -0 \(ProcessInfo.processInfo.processIdentifier) 2>/dev/null; then
                break
            fi
            sleep 0.1
        done

        rm -rf \(currentPath)
        cp -R \(sourcePath) \(currentPath)

        hdiutil detach \(mountPath) -force
        rm -f \(dmgPath)

        open \(currentPath)
        rm -- "$0"
        """

        let scriptURL = URL(fileURLWithPath: "/tmp/geocentric_install_update.sh")
        try scriptContent.write(to: scriptURL, atomically: true, encoding: .utf8)
        try fm.setAttributes([.posixPermissions: 0o755], ofItemAtPath: scriptURL.path)

        let task = Process()
        task.executableURL = URL(fileURLWithPath: "/bin/bash")
        task.arguments = [scriptURL.path]
        try task.run()

        DispatchQueue.main.async {
            NSApplication.shared.terminate(nil)
        }
    }

    private func validateMountedApp(_ appURL: URL) throws {
        let infoURL = appURL.appendingPathComponent("Contents/Info.plist")
        guard let info = NSDictionary(contentsOf: infoURL),
              info["CFBundleIdentifier"] as? String == "com.geocentric.agentos",
              info["CFBundleExecutable"] as? String == "Geocentric"
        else {
            throw NSError(domain: "AppUpdater", code: 4, userInfo: [NSLocalizedDescriptionKey: "Downloaded app bundle identity did not match Geocentric."])
        }

        let verify = try ProcessRunner.run(
            executable: "/usr/bin/codesign",
            arguments: ["--verify", "--deep", "--strict", appURL.path],
            currentDirectory: URL(fileURLWithPath: "/tmp")
        )
        guard verify.status == 0 else {
            throw NSError(domain: "AppUpdater", code: 5, userInfo: [NSLocalizedDescriptionKey: "Downloaded app failed code-signature verification."])
        }
    }

    private func shellQuoted(_ value: String) -> String {
        "'" + value.replacingOccurrences(of: "'", with: "'\\''") + "'"
    }
}
