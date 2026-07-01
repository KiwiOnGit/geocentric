import SwiftUI
import AppKit
import UniformTypeIdentifiers

struct SettingsView: View {
    @EnvironmentObject private var server: DesktopServer
    @EnvironmentObject private var appModel: NativeAppModel
    @StateObject private var updater = AppUpdater.shared

    @State private var googleClientID = ""
    @State private var googleClientSecret = ""
    @State private var isConfigSaved = false
    @State private var isGoogleLinked = false
    @State private var googleEmail = ""

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 24) {
                Text("Settings").geocentricOutlineShadow()
                    .font(.system(size: 26, weight: .semibold))

                VStack(alignment: .leading, spacing: 6) {
                    Text("Appearance & Performance").geocentricOutlineShadow()
                        .font(.system(size: 13, weight: .bold))
                        .foregroundStyle(.secondary)
                    VStack(alignment: .leading, spacing: 12) {
                        Toggle(isOn: $appModel.animatedBackgroundEnabled) {
                            VStack(alignment: .leading, spacing: 2) {
                                Text("Animated Watercolor Background").geocentricOutlineShadow()
                                    .font(.system(size: 13, weight: .medium))
                                Text("Disable animation to freeze background canvas and reduce CPU usage to absolute zero.").geocentricOutlineShadow()
                                    .font(.system(size: 11))
                                    .foregroundStyle(.secondary)
                            }
                        }
                        .toggleStyle(.checkbox)

                        Toggle(isOn: $appModel.soundEffectsEnabled) {
                            VStack(alignment: .leading, spacing: 2) {
                                Text("Enable Sound Effects").geocentricOutlineShadow()
                                    .font(.system(size: 13, weight: .medium))
                                Text("Play subtle audio feedback on message completion, clicks, and errors.").geocentricOutlineShadow()
                                    .font(.system(size: 11))
                                    .foregroundStyle(.secondary)
                            }
                        }
                        .toggleStyle(.checkbox)

                        Divider()
                            .padding(.vertical, 4)
                        
                        VStack(alignment: .leading, spacing: 8) {
                            Text("Theme Color").geocentricOutlineShadow()
                                .font(.system(size: 13, weight: .medium))
                            
                            HStack(spacing: 12) {
                                ForEach([
                                    ("blue", "Sapphire", Color(red: 0.1, green: 0.45, blue: 0.9)),
                                    ("emerald", "Emerald", Color(red: 0.1, green: 0.65, blue: 0.35)),
                                    ("sunset", "Sunset", Color(red: 0.95, green: 0.45, blue: 0.15)),
                                    ("violet", "Velvet", Color(red: 0.55, green: 0.25, blue: 0.85)),
                                    ("crimson", "Crimson", Color(red: 0.85, green: 0.15, blue: 0.25))
                                ], id: \.0) { key, label, color in
                                    Button {
                                        appModel.customAccentColor = key
                                    } label: {
                                        HStack(spacing: 5) {
                                            Circle()
                                                .fill(color)
                                                .frame(width: 10, height: 10)
                                            Text(label).font(.system(size: 11, weight: appModel.customAccentColor == key ? .bold : .regular))
                                                .foregroundStyle(.primary)
                                        }
                                        .padding(.horizontal, 8)
                                        .padding(.vertical, 4)
                                        .background(appModel.customAccentColor == key ? color.opacity(0.15) : Color.black.opacity(0.04))
                                        .clipShape(RoundedRectangle(cornerRadius: 6))
                                        .overlay {
                                            RoundedRectangle(cornerRadius: 6)
                                                .stroke(appModel.customAccentColor == key ? color : Color.clear, lineWidth: 1.5)
                                        }
                                    }
                                    .buttonStyle(.plain)
                                    .pointerHover()
                                }
                            }
                        }
                    }
                    .cardStyle()
                }
                
                VStack(alignment: .leading, spacing: 6) {
                    Text("System Metrics").geocentricOutlineShadow()
                        .font(.system(size: 13, weight: .bold))
                        .foregroundStyle(.secondary)
                    VStack(alignment: .leading, spacing: 14) {
                        Grid(alignment: .leading, horizontalSpacing: 16, verticalSpacing: 10) {
                            SettingsMetricRow(name: "CPU Load", value: appModel.telemetry.cpuPercent, tintColor: .blue)
                            SettingsMetricRow(name: "Memory", value: appModel.telemetry.memoryPercent, tintColor: .purple)
                            SettingsMetricRow(name: "Disk Space", value: appModel.telemetry.diskPercent, tintColor: .green)
                            if let gpu = appModel.telemetry.gpuPercent {
                                SettingsMetricRow(name: "GPU Load", value: gpu, tintColor: .orange)
                            }
                        }
                    }
                    .cardStyle()
                }

                VStack(alignment: .leading, spacing: 6) {
                    Text("Service Configuration").geocentricOutlineShadow()
                        .font(.system(size: 13, weight: .bold))
                        .foregroundStyle(.secondary)
                    VStack(alignment: .leading, spacing: 12) {
                        HStack {
                            Text("Access Mode").geocentricOutlineShadow()
                            Spacer()
                            Text(server.mode?.title ?? "Not selected").geocentricOutlineShadow()
                                .foregroundStyle(.secondary)
                        }
                        HStack {
                            Text("Agent Service").geocentricOutlineShadow()
                            Spacer()
                            Text(server.statusText).geocentricOutlineShadow()
                                .foregroundStyle(.secondary)
                                .lineLimit(1)
                        }
                        if server.mode == .localWiFi {
                            Divider()
                                .padding(.vertical, 4)
                            VStack(alignment: .leading, spacing: 8) {
                                Text("Local Wi-Fi Access Instructions").geocentricOutlineShadow()
                                    .font(.system(size: 13, weight: .bold))
                                
                                if let network = server.networkURL {
                                    Text("Connect other devices (phones, tablets, PCs) on the same Wi-Fi network by opening:")
                                        .font(.system(size: 11))
                                        .foregroundStyle(.secondary)
                                        .fixedSize(horizontal: false, vertical: true)
                                    HStack {
                                        Text(network.absoluteString)
                                            .font(.system(size: 12, weight: .semibold, design: .monospaced))
                                            .foregroundStyle(Color.geocentricAccent)
                                        Spacer()
                                        Button("Copy") {
                                            NSPasteboard.general.clearContents()
                                            NSPasteboard.general.setString(network.absoluteString, forType: .string)
                                        }
                                        .buttonStyle(.plain)
                                        .foregroundStyle(.secondary)
                                        .pointerHover()
                                    }
                                    .padding(6)
                                    .background(Color.black.opacity(0.05))
                                    .clipShape(RoundedRectangle(cornerRadius: 4))
                                } else {
                                    Text("Wi-Fi network URL not detected. Make sure this Mac is connected to a local Wi-Fi router.")
                                        .font(.system(size: 11))
                                        .foregroundStyle(.secondary)
                                        .fixedSize(horizontal: false, vertical: true)
                                }
                                
                                VStack(alignment: .leading, spacing: 4) {
                                    Text("VPN Troubleshooting:")
                                        .font(.system(size: 11, weight: .semibold))
                                        .foregroundStyle(.orange)
                                    Text("• Active VPNs will block local network connections.\n• Turn off VPNs on both the Mac and your other devices to connect, or configure your VPN client to allow local IP sharing / LAN bypass traffic.")
                                        .font(.system(size: 11))
                                        .foregroundStyle(.secondary)
                                        .fixedSize(horizontal: false, vertical: true)
                                }
                                .padding(.top, 4)
                            }
                        }
                        HStack {
                            Button("Choose Access Again") {
                                server.chooseAgain()
                            }
                            Button("Restart Agent Service") {
                                server.restart()
                            }
                        }
                    }
                    .cardStyle()
                }

                VStack(alignment: .leading, spacing: 6) {
                    HStack {
                        Text("Google Workspace Integration").geocentricOutlineShadow()
                            .font(.system(size: 13, weight: .bold))
                            .foregroundStyle(.secondary)
                        Spacer()
                        Button {
                            fetchGoogleConfig()
                        } label: {
                            Image(systemName: "arrow.clockwise").geocentricOutlineShadow()
                                .font(.system(size: 10))
                        }
                        .buttonStyle(.plain)
                        .pointerHover()
                        .help("Refresh Google status")
                    }
                    
                    VStack(alignment: .leading, spacing: 14) {
                        Text("Enable Geocentric agent to search and summarize emails, compose draft replies, and manage documents on Gmail and Google Docs.").geocentricOutlineShadow()
                            .font(.system(size: 12))
                            .foregroundStyle(.secondary)
                        
                        if isGoogleLinked {
                            HStack {
                                VStack(alignment: .leading, spacing: 4) {
                                    Text("Linked Google Account").geocentricOutlineShadow()
                                        .font(.system(size: 13, weight: .semibold))
                                    Text(googleEmail).geocentricOutlineShadow()
                                        .font(.system(size: 12))
                                        .foregroundStyle(.secondary)
                                }
                                Spacer()
                                Button("Disconnect Account") {
                                    disconnectGoogle()
                                }
                                .buttonStyle(.bordered)
                                .pointerHover()
                            }
                        } else {
                            VStack(alignment: .leading, spacing: 14) {
                                Button {
                                    signInWithGoogle()
                                } label: {
                                    HStack(spacing: 8) {
                                        Image(systemName: "safari").geocentricOutlineShadow()
                                        Text("Sign in with Google").geocentricOutlineShadow()
                                    }
                                }
                                .buttonStyle(.borderedProminent)
                                .pointerHover()
                                
                                DisclosureGroup("Advanced OAuth Settings") {
                                    VStack(alignment: .leading, spacing: 10) {
                                        Text("If Google blocks authentication with a 401 invalid_client error, configure your own Google Cloud Console client credentials below:").geocentricOutlineShadow()
                                            .font(.system(size: 11))
                                            .foregroundStyle(.secondary)
                                            .padding(.bottom, 4)
                                        
                                        Button {
                                            importCredentialsJSON()
                                        } label: {
                                            HStack {
                                                Image(systemName: "doc.badge.plus").geocentricOutlineShadow()
                                                Text("Upload client_secret.json...").geocentricOutlineShadow()
                                            }
                                        }
                                        .buttonStyle(.bordered)
                                        .pointerHover()
                                        
                                        Text("Or configure manually:").geocentricOutlineShadow()
                                            .font(.system(size: 10, weight: .bold))
                                            .foregroundStyle(.secondary)
                                            .padding(.top, 4)
                                        
                                        TextField("Google Client ID", text: $googleClientID)
                                            .textFieldStyle(.roundedBorder)
                                        
                                        SecureField("Google Client Secret (Leave empty to keep current)", text: $googleClientSecret)
                                            .textFieldStyle(.roundedBorder)
                                        
                                        HStack(spacing: 12) {
                                            Button("Save Credentials") {
                                                saveGoogleConfig()
                                            }
                                            .buttonStyle(.bordered)
                                            .pointerHover()
                                            
                                            if isConfigSaved {
                                                Text("Credentials Saved!").geocentricOutlineShadow()
                                                    .font(.system(size: 11, weight: .semibold))
                                                    .foregroundStyle(.green)
                                            }
                                        }
                                    }
                                    .padding(.top, 8)
                                }
                                .font(.system(size: 12))
                                .foregroundStyle(.secondary)
                            }
                        }
                    }
                    .cardStyle()
                }

                VStack(alignment: .leading, spacing: 6) {
                    Text("Application Updates").geocentricOutlineShadow()
                        .font(.system(size: 13, weight: .bold))
                        .foregroundStyle(.secondary)
                    VStack(alignment: .leading, spacing: 14) {
                        HStack {
                            VStack(alignment: .leading, spacing: 4) {
                                Text("Current Version").geocentricOutlineShadow()
                                    .font(.system(size: 14, weight: .medium))
                                Text("v\(updater.currentVersion)").geocentricOutlineShadow()
                                    .font(.system(size: 12))
                                    .foregroundStyle(.secondary)
                            }
                            Spacer()
                            
                            switch updater.state {
                            case .idle:
                                Button("Check for Updates") {
                                    updater.checkForUpdates()
                                }
                                .buttonStyle(.borderedProminent)
                            case .checking:
                                HStack(spacing: 8) {
                                    ProgressView().controlSize(.small)
                                    Text("Checking...").geocentricOutlineShadow()
                                        .font(.system(size: 13))
                                        .foregroundStyle(.secondary)
                                }
                            case .upToDate:
                                HStack(spacing: 8) {
                                    Image(systemName: "checkmark.circle.fill").geocentricOutlineShadow()
                                        .foregroundStyle(.green)
                                    Text("Up to date").geocentricOutlineShadow()
                                        .font(.system(size: 13, weight: .semibold))
                                    Button("Check Again") {
                                        updater.checkForUpdates()
                                    }
                                    .buttonStyle(.plain)
                                    .foregroundStyle(Color.geocentricAccent)
                                    .padding(.leading, 8)
                                }
                            case .updateAvailable(let version, let downloadURL, _):
                                VStack(alignment: .trailing, spacing: 6) {
                                    Text("v\(version) available").geocentricOutlineShadow()
                                        .font(.system(size: 13, weight: .semibold))
                                        .foregroundStyle(Color.geocentricAccent)
                                    Button("Update Now") {
                                        updater.downloadAndInstallUpdate(from: downloadURL)
                                    }
                                    .buttonStyle(.borderedProminent)
                                }
                            case .downloading(let progress):
                                VStack(alignment: .trailing, spacing: 6) {
                                    ProgressView(value: progress)
                                        .frame(width: 150)
                                    Text("Downloading (\(Int(progress * 100))%)").geocentricOutlineShadow()
                                        .font(.system(size: 11))
                                        .foregroundStyle(.secondary)
                                }
                            case .installing:
                                HStack(spacing: 8) {
                                    ProgressView().controlSize(.small)
                                    Text("Installing...").geocentricOutlineShadow()
                                        .font(.system(size: 13))
                                        .foregroundStyle(.secondary)
                                }
                            case .error(let message):
                                VStack(alignment: .trailing, spacing: 6) {
                                    Text(message).geocentricOutlineShadow()
                                        .font(.system(size: 12))
                                        .foregroundStyle(.red)
                                        .multilineTextAlignment(.trailing)
                                        .frame(maxWidth: 240)
                                    Button("Check Again") {
                                        updater.checkForUpdates()
                                    }
                                    .buttonStyle(.plain)
                                    .foregroundStyle(Color.geocentricAccent)
                                }
                            }
                        }
                        
                        if case .updateAvailable(_, _, let notes) = updater.state, let releaseNotes = notes, !releaseNotes.isEmpty {
                            Divider()
                            VStack(alignment: .leading, spacing: 6) {
                                Text("Release Notes:").geocentricOutlineShadow()
                                    .font(.system(size: 12, weight: .bold))
                                    .foregroundStyle(.secondary)
                                ScrollView {
                                    Text(releaseNotes).geocentricOutlineShadow()
                                        .font(.system(size: 12))
                                        .foregroundStyle(.secondary)
                                        .textSelection(.enabled)
                                        .frame(maxWidth: .infinity, alignment: .leading)
                                }
                                .frame(maxHeight: 120)
                            }
                        }
                    }
                    .cardStyle()
                }

                VStack(alignment: .leading, spacing: 6) {
                    Text("Danger Zone").geocentricOutlineShadow()
                        .font(.system(size: 13, weight: .bold))
                        .foregroundStyle(.red)
                    VStack(alignment: .leading, spacing: 12) {
                        HStack {
                            VStack(alignment: .leading, spacing: 4) {
                                Text("Clear All Chat Threads").geocentricOutlineShadow()
                                    .font(.system(size: 13, weight: .medium))
                                Text("This will permanently delete all conversation threads from your local database.").geocentricOutlineShadow()
                                    .font(.system(size: 11))
                                    .foregroundStyle(.secondary)
                            }
                            Spacer()
                            Button(role: .destructive) {
                                clearAllConversationsPrompt()
                            } label: {
                                Text("Delete All").foregroundStyle(.red)
                            }
                            .buttonStyle(.bordered)
                            .pointerHover()
                        }
                    }
                    .cardStyle()
                }
            }
            .padding(42)
            .frame(maxWidth: 760, alignment: .leading)
        }
        .onAppear {
            fetchGoogleConfig()
        }
    }

    private func fetchGoogleConfig() {
        guard let baseURL = server.localURL else { return }
        Task {
            do {
                let data = try await appModel.apiClient.authenticatedGetJSON(baseURL: baseURL, path: "api/auth/google/config")
                struct GoogleConfigResponse: Codable {
                    let clientId: String
                    let clientSecret: String
                    let isLinked: Bool
                    let email: String
                }
                let resp = try JSONDecoder().decode(GoogleConfigResponse.self, from: data)
                DispatchQueue.main.async {
                    if resp.clientId.contains("dummy") {
                        self.googleClientID = ""
                    } else {
                        self.googleClientID = resp.clientId
                    }
                    self.isGoogleLinked = resp.isLinked
                    self.googleEmail = resp.email
                }
            } catch {
                print("Failed to fetch Google config: \(error)")
            }
        }
    }

    private func saveGoogleConfig() {
        guard let baseURL = server.localURL else { return }
        Task {
            do {
                _ = try await appModel.apiClient.authenticatedPostJSON(
                    baseURL: baseURL,
                    path: "api/auth/google/config",
                    body: [
                        "clientId": googleClientID,
                        "clientSecret": googleClientSecret
                    ]
                )
                DispatchQueue.main.async {
                    self.isConfigSaved = true
                    DispatchQueue.main.asyncAfter(deadline: .now() + 2) {
                        self.isConfigSaved = false
                    }
                    fetchGoogleConfig()
                }
            } catch {
                print("Failed to save Google config: \(error)")
            }
        }
    }

    private func importCredentialsJSON() {
        let panel = NSOpenPanel()
        panel.allowsMultipleSelection = false
        panel.canChooseDirectories = false
        panel.canChooseFiles = true
        panel.allowedContentTypes = [.json]
        
        panel.begin { response in
            if response == .OK, let url = panel.url {
                do {
                    let data = try Data(contentsOf: url)
                    if let json = try JSONSerialization.jsonObject(with: data) as? [String: Any] {
                        var clientID: String?
                        var clientSecret: String?
                        
                        if let installed = json["installed"] as? [String: Any] {
                            clientID = installed["client_id"] as? String
                            clientSecret = installed["client_secret"] as? String
                        } else if let web = json["web"] as? [String: Any] {
                            clientID = web["client_id"] as? String
                            clientSecret = web["client_secret"] as? String
                        } else {
                            clientID = json["client_id"] as? String
                            clientSecret = json["client_secret"] as? String
                        }
                        
                        if let cid = clientID, let sec = clientSecret {
                            DispatchQueue.main.async {
                                self.googleClientID = cid
                                self.googleClientSecret = sec
                                self.saveGoogleConfig()
                            }
                        } else {
                            print("Invalid credentials JSON format.")
                        }
                    }
                } catch {
                    print("Failed to read credentials file: \(error)")
                }
            }
        }
    }

    private func signInWithGoogle() {
        guard let baseURL = server.localURL else { return }
        Task {
            do {
                _ = try? await appModel.apiClient.authenticatedGetJSON(baseURL: baseURL, path: "api/auth/google/config")
                let token = try await appModel.apiClient.ensureSession(baseURL: baseURL)
                let loginURL = baseURL.appendingPathComponent("api/auth/google/login")
                var components = URLComponents(url: loginURL, resolvingAgainstBaseURL: true)
                components?.queryItems = [URLQueryItem(name: "token", value: token)]
                if let url = components?.url {
                    NSWorkspace.shared.open(url)
                }
            } catch {
                print("Failed to start Google login: \(error)")
            }
        }
    }

    private func disconnectGoogle() {
        guard let baseURL = server.localURL else { return }
        Task {
            do {
                _ = try await appModel.apiClient.authenticatedPostJSON(
                    baseURL: baseURL,
                    path: "api/auth/google/disconnect",
                    body: [:]
                )
                DispatchQueue.main.async {
                    self.isGoogleLinked = false
                    self.googleEmail = ""
                }
            } catch {
                print("Failed to disconnect Google: \(error)")
            }
        }
    }

    private func clearAllConversationsPrompt() {
        let alert = NSAlert()
        alert.messageText = "Delete All Threads?"
        alert.informativeText = "Are you sure you want to permanently delete all conversation threads? This action cannot be undone."
        alert.alertStyle = .critical
        alert.addButton(withTitle: "Delete All")
        alert.addButton(withTitle: "Cancel")
        
        if alert.runModal() == .alertFirstButtonReturn {
            appModel.clearAllConversations()
        }
    }
}

struct SettingsMetricRow: View {
    let name: String
    let value: Double
    let tintColor: Color

    var body: some View {
        GridRow {
            Text(name)
                .font(.system(size: 12, weight: .semibold))
                .foregroundStyle(.primary)
            
            GeometryReader { geo in
                ZStack(alignment: .leading) {
                    RoundedRectangle(cornerRadius: 4)
                        .fill(Color.black.opacity(0.12))
                        .frame(height: 7)
                    
                    RoundedRectangle(cornerRadius: 4)
                        .fill(
                            LinearGradient(
                                colors: [tintColor, tintColor.opacity(0.72)],
                                startPoint: .leading,
                                endPoint: .trailing
                            )
                        )
                        .frame(width: max(4, geo.size.width * CGFloat(min(100, max(0, value)) / 100.0)), height: 7)
                        .shadow(color: tintColor.opacity(0.2), radius: 2, x: 0, y: 1)
                }
                .frame(maxHeight: .infinity, alignment: .center)
            }
            .frame(minWidth: 180, minHeight: 14)
            
            Text("\(Int(value))%")
                .font(.system(size: 11.5, weight: .bold, design: .monospaced))
                .foregroundStyle(.secondary)
        }
    }
}
