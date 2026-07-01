import SwiftUI

struct RootView: View {
    @EnvironmentObject private var server: DesktopServer
    @EnvironmentObject private var ollama: OllamaManager
    @EnvironmentObject private var appModel: NativeAppModel

    private var isInstallerMode: Bool {
        let bundleURL = Bundle.main.bundleURL
        return !bundleURL.path.contains("/Applications/") && !bundleURL.path.contains("/geocentric/mac_app")
    }

    var body: some View {
        ZStack {
            FlowingGradientView()

            if isInstallerMode {
                DMGInstallerWindowView()
            } else if server.mode == nil {
                StartupChoiceView()
            } else {
                NativeWorkspaceView()
                    .sheet(isPresented: $appModel.showModels) {
                        ModelManagerSheet()
                            .environmentObject(ollama)
                            .environmentObject(appModel)
                            .frame(minWidth: 760, minHeight: 560)
                    }
                    .sheet(item: $appModel.activeServicePanel) { panel in
                        ServiceDetailsSheet(panel: panel)
                            .environmentObject(server)
                            .environmentObject(ollama)
                            .environmentObject(appModel)
                            .frame(minWidth: 680, minHeight: 460)
                    }
            }
        }
        .tint(Color.geocentricAccent)
        .accentColor(Color.geocentricAccent)
    }
}

struct StartupChoiceView: View {
    @EnvironmentObject private var server: DesktopServer

    var body: some View {
        VStack(spacing: 28) {
            Spacer(minLength: 40)
            VStack(spacing: 14) {
                AppMark(size: 72)
                Text("Geocentric").geocentricOutlineShadow()
                    .font(.system(size: 34, weight: .semibold))
                Text("Choose how the local agent service should be hosted for this launch.").geocentricOutlineShadow()
                    .font(.system(size: 15))
                    .foregroundStyle(.secondary)
            }

            HStack(spacing: 14) {
                ForEach(AccessMode.allCases) { mode in
                    Button {
                        server.start(mode: mode)
                    } label: {
                        AccessModeCard(mode: mode)
                    }
                    .buttonStyle(.plain)
                }
            }
            .frame(maxWidth: 740)

            Text("The desktop app stays native either way. Local Wi-Fi only affects the background service for trusted devices on your network.").geocentricOutlineShadow()
                .font(.system(size: 12))
                .foregroundStyle(.tertiary)
                .multilineTextAlignment(.center)
                .frame(maxWidth: 580)
            Spacer(minLength: 40)
        }
        .padding(36)
    }
}

struct AccessModeCard: View {
    let mode: AccessMode

    var body: some View {
        VStack(alignment: .leading, spacing: 18) {
            Image(systemName: mode.icon).geocentricOutlineShadow()
                .font(.system(size: 28, weight: .medium))
                .foregroundStyle(Color.geocentricAccent)
                .frame(width: 54, height: 54)
                .background(Color.geocentricAccent.opacity(0.12))
                .clipShape(RoundedRectangle(cornerRadius: 8))
            VStack(alignment: .leading, spacing: 8) {
                Text(mode.title).geocentricOutlineShadow()
                    .font(.system(size: 19, weight: .semibold))
                Text(mode.subtitle).geocentricOutlineShadow()
                    .font(.system(size: 13))
                    .foregroundStyle(.secondary)
                    .fixedSize(horizontal: false, vertical: true)
            }
            Spacer()
            HStack {
                Text(mode.bindHost).geocentricOutlineShadow()
                    .font(.system(size: 12, design: .monospaced))
                    .foregroundStyle(.secondary)
                Spacer()
                Image(systemName: "arrow.right.circle.fill").geocentricOutlineShadow()
                    .font(.system(size: 22, weight: .semibold))
                    .foregroundStyle(Color.geocentricAccent)
            }
        }
        .padding(22)
        .frame(maxWidth: .infinity, minHeight: 205, alignment: .topLeading)
        .liquidGlass(cornerRadius: 12)
    }
}

struct NativeWorkspaceView: View {
    @EnvironmentObject private var server: DesktopServer
    @EnvironmentObject private var ollama: OllamaManager
    @EnvironmentObject private var appModel: NativeAppModel

    @Environment(\.colorScheme) private var colorScheme

    private var leftButtonColor: Color {
        if appModel.sidebarVisible {
            return .white
        } else {
            return colorScheme == .dark ? .white : .primary
        }
    }

    private var rightButtonColor: Color {
        colorScheme == .dark ? .white : .primary
    }

    var body: some View {
        HStack(spacing: 0) {
            if appModel.sidebarVisible {
                SidebarDrawer()
                    .environmentObject(appModel)
                    .transition(.move(edge: .leading).combined(with: .opacity))
            }

            mainContent
                .frame(maxWidth: .infinity, maxHeight: .infinity)
                .background(Color.black.opacity(0.22))
        }
        .onAppear {
            server.startIfNeeded()
        }
        .toolbar {
            ToolbarItemGroup(placement: .navigation) {
                Button {
                    appModel.playSound("Tink")
                    withAnimation(.spring(response: 0.24, dampingFraction: 0.88)) {
                        appModel.sidebarVisible.toggle()
                    }
                } label: {
                    Image(systemName: "sidebar.leading").geocentricOutlineShadow()
                        .foregroundStyle(leftButtonColor)
                }
                .help(appModel.sidebarVisible ? "Hide Navigation Panel" : "Show Navigation Panel")

                Button {
                    appModel.playSound("Tink")
                    appModel.selectAdjacentConversation(offset: -1)
                } label: {
                    Image(systemName: "chevron.left").geocentricOutlineShadow()
                        .foregroundStyle(leftButtonColor)
                }
                .disabled(!canGoBack)
                .help("Previous Conversation")

                Button {
                    appModel.playSound("Tink")
                    appModel.selectAdjacentConversation(offset: 1)
                } label: {
                    Image(systemName: "chevron.right").geocentricOutlineShadow()
                        .foregroundStyle(leftButtonColor)
                }
                .disabled(!canGoForward)
                .help("Next Conversation")
            }

            ToolbarItemGroup(placement: .status) {
                HStack(spacing: 8) {
                    ModelToolbarMenu()
                        .environmentObject(ollama)
                        .environmentObject(appModel)

                    ContextGauge()
                        .environmentObject(appModel)

                    Button {
                        appModel.playSound("Tink")
                        if server.isUsable {
                            appModel.activeServicePanel = .agent
                        } else {
                            server.startIfNeeded()
                        }
                    } label: {
                        HStack(spacing: 4) {
                            Circle()
                                .fill(agentStatusColor)
                                .frame(width: 7, height: 7)
                            Text(agentStatusText).geocentricOutlineShadow()
                                .font(.system(size: 11, weight: .medium))
                        }
                        .padding(.horizontal, 6)
                        .padding(.vertical, 3)
                        .toolbarStatusChip()
                    }
                    .buttonStyle(.plain)
                    .help(server.isUsable ? "Agent Service Status" : "Start Agent Service")
                }
            }

            ToolbarItemGroup(placement: .primaryAction) {
                Button {
                    appModel.playSound("Pop")
                    appModel.newConversation()
                } label: {
                    Label("New Chat", systemImage: "square.and.pencil").geocentricOutlineShadow()
                        .foregroundStyle(rightButtonColor)
                }
                .help("New Conversation")
            }
        }
    }
    @ViewBuilder
    private var mainContent: some View {
        switch appModel.selectedSection {
        case .chat:
            ConversationView()
        case .history:
            HistoryView()
        case .tasks:
            ScheduledTasksView()
        case .models:
            ModelsPageView()
        case .settings:
            SettingsView()
        }
    }

    private var canGoBack: Bool {
        let ordered = appModel.recentConversations
        guard let currentID = appModel.selectedConversationID,
              let current = ordered.firstIndex(where: { $0.id == currentID })
        else { return false }
        return current > 0
    }

    private var canGoForward: Bool {
        let ordered = appModel.recentConversations
        guard let currentID = appModel.selectedConversationID,
              let current = ordered.firstIndex(where: { $0.id == currentID })
        else { return false }
        return current < ordered.count - 1
    }

    private var agentStatusText: String {
        if server.isUsable {
            return "Agent: Ready"
        }
        switch server.state {
        case .running:
            return "Agent: Ready"
        case .preparing, .installing, .starting:
            return "Agent: Starting"
        case .stopping:
            return "Agent: Stopping"
        case .choosing:
            return "Agent: Start"
        case .failed:
            return "Agent: Issue"
        }
    }

    private var agentStatusColor: Color {
        if server.isUsable {
            return .green
        }
        switch server.state {
        case .running:
            return .green
        case .preparing, .installing, .starting, .stopping, .choosing:
            return .orange
        case .failed:
            return .red
        }
    }
}

struct SidebarDrawer: View {
    @EnvironmentObject private var appModel: NativeAppModel

    var body: some View {
        VStack(spacing: 0) {
            HStack(spacing: 10) {
                AppMark(size: 28)
                Text("Geocentric")
                    .font(.system(size: 13, weight: .bold))
                Spacer()
                Button {
                    appModel.newConversation()
                } label: {
                    Label("New Chat", systemImage: "square.and.pencil")
                }
                .buttonStyle(.borderless)
                .help("New Conversation")
            }
            .padding(.horizontal, 14)
            .padding(.top, 14)
            .padding(.bottom, 8)

            SidebarView()
        }
        .frame(width: 292)
        .frame(maxHeight: .infinity)
        .background(Color.black.opacity(0.58))
        .foregroundStyle(Color.white.opacity(0.92))
        .overlay(alignment: .trailing) {
            Rectangle()
                .fill(Color.black.opacity(0.34))
                .frame(width: 1)
        }
        .shadow(color: Color.black.opacity(0.22), radius: 28, x: 12, y: 0)
    }
}

struct ModelToolbarMenu: View {
    @EnvironmentObject private var ollama: OllamaManager
    @EnvironmentObject private var appModel: NativeAppModel
    @State private var showingPicker = false
    @State private var query = ""

    private var filteredModels: [OllamaModel] {
        let trimmed = query.trimmingCharacters(in: .whitespacesAndNewlines).lowercased()
        guard !trimmed.isEmpty else { return ollama.installedModels }
        return ollama.installedModels.filter {
            $0.displayName.lowercased().contains(trimmed)
                || $0.name.lowercased().contains(trimmed)
                || ($0.detailLine.lowercased().contains(trimmed))
        }
    }

    var body: some View {
        Button {
            showingPicker.toggle()
        } label: {
            HStack(spacing: 5) {
                Circle()
                    .fill(ollama.hasSelectedInstalledModel ? Color.green : Color.orange)
                    .frame(width: 7, height: 7)
                Text(ollama.selectedModel.isEmpty ? "Model" : formatModelName(ollama.selectedModel)).geocentricOutlineShadow()
                    .font(.system(size: 11, weight: .medium))
                    .lineLimit(1)
                Image(systemName: "chevron.down").geocentricOutlineShadow()
                    .font(.system(size: 8, weight: .bold))
                    .foregroundStyle(.secondary)
            }
            .padding(.horizontal, 6)
            .padding(.vertical, 3)
            .toolbarStatusChip()
        }
        .buttonStyle(.plain)
        .popover(isPresented: $showingPicker, arrowEdge: .top) {
            VStack(alignment: .leading, spacing: 12) {
                HStack {
                    VStack(alignment: .leading, spacing: 2) {
                        Text("Models")
                            .font(.system(size: 15, weight: .semibold))
                        Text(ollama.statusText)
                            .font(.system(size: 11))
                            .foregroundStyle(.secondary)
                            .lineLimit(1)
                    }
                    Spacer()
                    Button {
                        ollama.refreshModels(startIfNeeded: false)
                    } label: {
                        Image(systemName: "arrow.clockwise")
                            .frame(width: 24, height: 24)
                    }
                    .buttonStyle(.plain)
                    .help("Refresh Models")
                }

                HStack(spacing: 7) {
                    Image(systemName: "magnifyingglass")
                        .font(.system(size: 11, weight: .semibold))
                        .foregroundStyle(.secondary)
                    TextField("Filter models", text: $query)
                        .textFieldStyle(.plain)
                    if !query.isEmpty {
                        Button {
                            query = ""
                        } label: {
                            Image(systemName: "xmark.circle.fill")
                                .font(.system(size: 11))
                                .foregroundStyle(.secondary)
                        }
                        .buttonStyle(.plain)
                    }
                }
                .padding(.horizontal, 9)
                .frame(height: 28)
                .background(Color.black.opacity(0.055))
                .clipShape(RoundedRectangle(cornerRadius: 6))

                if ollama.installedModels.isEmpty {
                    VStack(alignment: .leading, spacing: 8) {
                        Text("No local models downloaded.")
                            .font(.system(size: 13, weight: .semibold))
                        Text("Download a model to enable local chat.")
                            .font(.system(size: 12))
                            .foregroundStyle(.secondary)
                    }
                    .frame(maxWidth: .infinity, alignment: .leading)
                    .padding(.vertical, 8)
                } else {
                    ScrollView {
                        LazyVStack(alignment: .leading, spacing: 4) {
                            if filteredModels.isEmpty {
                                Text("No models match your filter.")
                                    .font(.system(size: 12))
                                    .foregroundStyle(.secondary)
                                    .frame(maxWidth: .infinity, alignment: .leading)
                                    .padding(.vertical, 10)
                            } else {
                                ForEach(filteredModels) { model in
                                    ModelQuickPickRow(
                                        model: model,
                                        selected: model.matches(ollama.selectedModel),
                                        deleting: ollama.deletingModel == model.name
                                    ) {
                                        ollama.selectModel(model.name)
                                        showingPicker = false
                                    }
                                }
                            }
                        }
                    }
                    .frame(maxHeight: 280)
                }

                HStack {
                    Button("Manage Models...") {
                        showingPicker = false
                        appModel.showModels = true
                    }
                    .buttonStyle(.bordered)

                    Spacer()

                    Button(ollama.installedModels.isEmpty ? "Download Model..." : "Download More...") {
                        showingPicker = false
                        appModel.showModels = true
                    }
                    .buttonStyle(.borderedProminent)
                }
            }
            .padding(14)
            .frame(width: 360)
        }
        .help("Select Active Model")
    }
}

private struct ModelQuickPickRow: View {
    let model: OllamaModel
    let selected: Bool
    let deleting: Bool
    let action: () -> Void

    var body: some View {
        Button(action: action) {
            HStack(spacing: 9) {
                Image(systemName: selected ? "checkmark.circle.fill" : "cube.box")
                    .font(.system(size: 13, weight: .semibold))
                    .foregroundStyle(selected ? Color.green : Color.secondary)
                    .frame(width: 18)
                VStack(alignment: .leading, spacing: 2) {
                    Text(model.displayName)
                        .font(.system(size: 13, weight: .semibold))
                        .lineLimit(1)
                    if !model.detailLine.isEmpty {
                        Text(model.detailLine)
                            .font(.system(size: 11))
                            .foregroundStyle(.secondary)
                            .lineLimit(1)
                    }
                }
                Spacer()
                if deleting {
                    ProgressView()
                        .controlSize(.small)
                }
            }
            .contentShape(Rectangle())
            .padding(.horizontal, 8)
            .padding(.vertical, 7)
            .background(selected ? Color.green.opacity(0.10) : Color.clear)
            .clipShape(RoundedRectangle(cornerRadius: 6))
        }
        .buttonStyle(.plain)
        .disabled(deleting)
    }
}

struct ContextGauge: View {
    @EnvironmentObject private var appModel: NativeAppModel

    private var ratio: Double { appModel.contextUsageRatio }

    var body: some View {
        Button {
            if ratio >= 0.8 {
                appModel.compactContext()
            }
        } label: {
            HStack(spacing: 6) {
                ZStack {
                    Circle()
                        .stroke(Color.primary.opacity(0.14), lineWidth: 3)
                    Circle()
                        .trim(from: 0, to: ratio)
                        .stroke(ratio >= 0.8 ? Color.orange : Color.green, style: StrokeStyle(lineWidth: 3, lineCap: .round))
                        .rotationEffect(.degrees(-90))
                    Text("\(Int(ratio * 100))").geocentricOutlineShadow()
                        .font(.system(size: 7, weight: .bold))
                }
                .frame(width: 22, height: 22)
                Text("Context").geocentricOutlineShadow()
                    .font(.system(size: 11, weight: .medium))
            }
            .foregroundStyle(.primary)
            .padding(.horizontal, 7)
            .padding(.vertical, 3)
            .toolbarStatusChip()
        }
        .buttonStyle(.plain)
        .help(ratio >= 0.8 ? "Compact context" : "Context usage")
    }
}

extension View {
    func toolbarStatusChip() -> some View {
        self
            .foregroundStyle(.primary)
            .background(Color.white.opacity(0.72))
            .clipShape(Capsule())
            .overlay {
                Capsule()
                    .stroke(Color.black.opacity(0.34), lineWidth: 1)
            }
            .shadow(color: Color.black.opacity(0.05), radius: 5, y: 1)
    }
}

struct DMGInstallerWindowView: View {
    @EnvironmentObject private var server: DesktopServer
    @State private var statusText = "Ready to install"
    @State private var isInstalling = false
    
    private var destinationURL: URL {
        URL(fileURLWithPath: "/Applications/Geocentric.app")
    }
    
    private var isAppAlreadyInstalled: Bool {
        FileManager.default.fileExists(atPath: destinationURL.path)
    }
    
    var body: some View {
        VStack(spacing: 20) {
            Spacer()
            
            AppMark(size: 80)
                .shadow(color: Color.black.opacity(0.15), radius: 10, y: 5)
            
            VStack(spacing: 6) {
                Text("Geocentric Installer").geocentricOutlineShadow()
                    .font(.system(size: 22, weight: .bold))
                
                Text(isAppAlreadyInstalled ? "An existing version was detected in /Applications." : "Install Geocentric to Applications to begin.")
                    .font(.system(size: 13))
                    .foregroundStyle(.secondary)
                    .multilineTextAlignment(.center)
                    .frame(maxWidth: 320)
            }
            
            if isInstalling {
                VStack(spacing: 10) {
                    ProgressView().controlSize(.small)
                    Text(statusText)
                        .font(.system(size: 12))
                        .foregroundStyle(.secondary)
                }
                .padding(.top, 10)
            } else {
                VStack(spacing: 12) {
                    HStack(spacing: 14) {
                        Button {
                            performInstallation()
                        } label: {
                            Text(isAppAlreadyInstalled ? "Update / Reinstall" : "Install")
                                .font(.system(size: 13, weight: .semibold))
                                .frame(width: 140, height: 32)
                        }
                        .buttonStyle(.borderedProminent)
                        .pointerHover()
                        
                        Button {
                            // Run from DMG, bypass installation
                            server.start(mode: .deviceOnly)
                        } label: {
                            Text("Run from DMG")
                                .font(.system(size: 13))
                                .frame(width: 140, height: 32)
                        }
                        .buttonStyle(.bordered)
                        .pointerHover()
                    }
                    
                    Button("Quit") {
                        NSApplication.shared.terminate(nil)
                    }
                    .buttonStyle(.plain)
                    .foregroundStyle(.secondary)
                    .pointerHover()
                }
                .padding(.top, 10)
            }
            
            Spacer()
        }
        .padding(24)
        .frame(width: 440, height: 340)
    }
    
    private func performInstallation() {
        isInstalling = true
        statusText = "Preparing installation..."
        
        DispatchQueue.global(qos: .userInitiated).async {
            let bundleURL = Bundle.main.bundleURL
            
            do {
                if isAppAlreadyInstalled {
                    DispatchQueue.main.async { statusText = "Removing older version..." }
                    try FileManager.default.removeItem(at: destinationURL)
                }
                
                DispatchQueue.main.async { statusText = "Copying Geocentric..." }
                try FileManager.default.copyItem(at: bundleURL, to: destinationURL)
                
                DispatchQueue.main.async {
                    statusText = "Relaunching from Applications..."
                    
                    // Relaunch the new application
                    let process = Process()
                    process.executableURL = URL(fileURLWithPath: "/usr/bin/open")
                    process.arguments = [destinationURL.path]
                    try? process.run()
                    
                    // Terminate current one
                    NSApplication.shared.terminate(nil)
                }
            } catch {
                DispatchQueue.main.async {
                    isInstalling = false
                    let alert = NSAlert()
                    alert.messageText = "Installation Failed"
                    alert.informativeText = error.localizedDescription
                    alert.runModal()
                }
            }
        }
    }
}
