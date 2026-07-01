import SwiftUI
import AppKit

struct ModelManagerSheet: View {
    var showsDone = true
    @EnvironmentObject private var ollama: OllamaManager
    @EnvironmentObject private var appModel: NativeAppModel
    @Environment(\.dismiss) private var dismiss

    var body: some View {
        VStack(spacing: 0) {
            HStack {
                VStack(alignment: .leading, spacing: 4) {
                    Text("Models").geocentricOutlineShadow()
                        .font(.system(size: 24, weight: .semibold))
                    Text("Install Ollama, download local models, and choose what Geocentric uses.").geocentricOutlineShadow()
                        .font(.system(size: 13))
                        .foregroundStyle(.secondary)
                }
                Spacer()
                if showsDone {
                    Button("Done") { dismiss() }
                }
            }
            .padding(24)

            Divider()

            ScrollView {
                LazyVStack(alignment: .leading, spacing: 20) {
                    OllamaInstallCard()
                    InstalledModelsCard()
                    SuggestedModelsCard()
                    FallbackAPIKeyCard()
                }
                .padding(24)
            }
        }
        .background(
            ZStack {
                VisualEffectView(material: .hudWindow, blendingMode: .withinWindow)
                Color.white.opacity(0.12)
            }
        )
    }
}

struct FallbackAPIKeyCard: View {
    @EnvironmentObject private var appModel: NativeAppModel
    @State private var baseURL = ""
    @State private var apiKey = ""
    @State private var model = ""

    var body: some View {
        VStack(alignment: .leading, spacing: 14) {
            VStack(alignment: .leading, spacing: 4) {
                Text("Fallback API").geocentricOutlineShadow()
                    .font(.system(size: 16, weight: .semibold))
                Text("Used only when Ollama has no selected local model.").geocentricOutlineShadow()
                    .font(.system(size: 13))
                    .foregroundStyle(.secondary)
            }

            Grid(horizontalSpacing: 12, verticalSpacing: 10) {
                GridRow {
                    Text("Base URL").geocentricOutlineShadow()
                        .foregroundStyle(.secondary)
                    TextField("https://api.openai.com/v1", text: $baseURL)
                        .textFieldStyle(.roundedBorder)
                }
                GridRow {
                    Text("Model").geocentricOutlineShadow()
                        .foregroundStyle(.secondary)
                    TextField("provider-model-name", text: $model)
                        .textFieldStyle(.roundedBorder)
                }
                GridRow {
                    Text("API Key").geocentricOutlineShadow()
                        .foregroundStyle(.secondary)
                    SecureField("Fallback API key", text: $apiKey)
                        .textFieldStyle(.roundedBorder)
                }
            }
            .font(.system(size: 13))

            HStack {
                Button("Save Fallback") {
                    appModel.saveFallbackAPI(baseURL: baseURL, apiKey: apiKey, model: model)
                }
                Button("Clear") {
                    baseURL = "https://api.openai.com/v1"
                    apiKey = ""
                    model = ""
                    appModel.saveFallbackAPI(baseURL: baseURL, apiKey: apiKey, model: model)
                }
                Spacer()
                Text(appModel.fallbackAPI.isConfigured ? "Configured" : "Not configured").geocentricOutlineShadow()
                    .font(.system(size: 12, weight: .medium))
                    .foregroundStyle(appModel.fallbackAPI.isConfigured ? .green : .secondary)
            }

            Label("API keys are stored in macOS Keychain.", systemImage: "lock.shield")
                .font(.system(size: 11, weight: .medium))
                .foregroundStyle(.secondary)
        }
        .cardStyle()
        .onAppear {
            baseURL = appModel.fallbackAPI.baseURL
            apiKey = appModel.fallbackAPI.apiKey
            model = appModel.fallbackAPI.model
        }
    }
}

struct ServiceDetailsSheet: View {
    let panel: ServicePanel
    @EnvironmentObject private var server: DesktopServer
    @EnvironmentObject private var ollama: OllamaManager
    @EnvironmentObject private var appModel: NativeAppModel
    @Environment(\.dismiss) private var dismiss

    var body: some View {
        VStack(spacing: 0) {
            HStack {
                VStack(alignment: .leading, spacing: 4) {
                    Text(panel == .ollama ? "Ollama Connection" : "Agent Service").geocentricOutlineShadow()
                        .font(.system(size: 23, weight: .semibold))
                    Text(panel == .ollama ? ollama.statusText : server.statusText).geocentricOutlineShadow()
                        .font(.system(size: 13))
                        .foregroundStyle(.secondary)
                        .lineLimit(2)
                }
                Spacer()
                Button("Done") { dismiss() }
            }
            .padding(24)
            Divider()
            LazyVStack(alignment: .leading, spacing: 16) {
                if panel == .ollama {
                    OllamaInstallCard()
                    InstalledModelsCard()
                    FallbackAPIKeyCard()
                } else {
                    VStack(alignment: .leading, spacing: 10) {
                        HStack {
                            Text("Mode").geocentricOutlineShadow()
                            Spacer()
                            Text(server.mode?.title ?? "Not selected").geocentricOutlineShadow().foregroundStyle(.secondary)
                        }
                        HStack {
                            Text("Local URL").geocentricOutlineShadow()
                            Spacer()
                            Text(server.localURL?.absoluteString ?? "Unavailable").geocentricOutlineShadow().foregroundStyle(.secondary)
                        }
                        if server.mode == .localWiFi {
                            VStack(alignment: .leading, spacing: 8) {
                                Divider()
                                    .padding(.vertical, 4)
                                VStack(alignment: .leading, spacing: 6) {
                                    Text("Wi-Fi Sharing Details").geocentricOutlineShadow()
                                        .font(.system(size: 13, weight: .semibold))
                                    if let network = server.networkURL {
                                        Text("To connect another device on your local Wi-Fi, point its browser or API client to:")
                                            .font(.system(size: 12))
                                            .foregroundStyle(.secondary)
                                            .fixedSize(horizontal: false, vertical: true)
                                        HStack {
                                            Text(network.absoluteString)
                                                .font(.system(size: 13, weight: .bold, design: .monospaced))
                                                .foregroundStyle(Color.accentColor)
                                            Spacer()
                                            Button("Copy") {
                                                NSPasteboard.general.clearContents()
                                                NSPasteboard.general.setString(network.absoluteString, forType: .string)
                                            }
                                            .buttonStyle(.plain)
                                            .foregroundStyle(.secondary)
                                            .pointerHover()
                                        }
                                        .padding(8)
                                        .background(Color.black.opacity(0.12))
                                        .clipShape(RoundedRectangle(cornerRadius: 6))
                                    } else {
                                        Text("No Wi-Fi network address found. Ensure your Mac is connected to Wi-Fi.")
                                            .font(.system(size: 12))
                                            .foregroundStyle(.secondary)
                                    }
                                    
                                    HStack(alignment: .top, spacing: 6) {
                                        Image(systemName: "exclamationmark.triangle")
                                            .font(.system(size: 11, weight: .semibold))
                                            .foregroundStyle(.orange)
                                        Text("VPNs active on either your Mac or connecting devices will break local connections unless local IP sharing/bypass is enabled in your VPN settings.")
                                            .font(.system(size: 11))
                                            .foregroundStyle(.orange)
                                            .fixedSize(horizontal: false, vertical: true)
                                    }
                                    .padding(.top, 4)
                                }
                            }
                        }
                        HStack {
                            Button("Restart") { server.restart() }
                            Button("Choose Access Again") {
                                dismiss()
                                server.chooseAgain()
                            }
                        }
                    }
                    .cardStyle()

                    LogCard(title: "Agent Logs", logs: server.logs)
                }
            }
            .padding(24)
            Spacer()
        }
        .background(
            ZStack {
                VisualEffectView(material: .hudWindow, blendingMode: .withinWindow)
                Color.white.opacity(0.12)
            }
        )
    }
}

struct LogCard: View {
    let title: String
    let logs: [String]

    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            Text(title).geocentricOutlineShadow()
                .font(.system(size: 16, weight: .semibold))
            ScrollView {
                Text(logs.isEmpty ? "No logs yet." : logs.suffix(80).joined(separator: "\n")).geocentricOutlineShadow()
                    .font(.system(size: 11, design: .monospaced))
                    .foregroundStyle(.secondary)
                    .frame(maxWidth: .infinity, alignment: .leading)
                    .textSelection(.enabled)
            }
            .frame(minHeight: 180)
            .padding(10)
            .background(Color.black.opacity(0.04))
            .clipShape(RoundedRectangle(cornerRadius: 7))
        }
        .cardStyle()
    }
}

struct OllamaInstallCard: View {
    @EnvironmentObject private var ollama: OllamaManager

    var body: some View {
        VStack(alignment: .leading, spacing: 14) {
            HStack {
                VStack(alignment: .leading, spacing: 5) {
                    Text("Ollama Runtime").geocentricOutlineShadow()
                        .font(.system(size: 16, weight: .semibold))
                    Text(ollama.statusText).geocentricOutlineShadow()
                        .font(.system(size: 13))
                        .foregroundStyle(.secondary)
                }
                Spacer()
                if ollama.state.isBusy {
                    ProgressView()
                }
                Button(ollama.isReady ? "Refresh" : "Install Ollama") {
                    if ollama.isReady {
                        ollama.refreshModels()
                    } else {
                        ollama.installOllama()
                    }
                }
                .disabled(ollama.state.isBusy)
            }

            if !ollama.logs.isEmpty {
                ScrollView {
                    Text(ollama.logs.suffix(12).joined(separator: "\n")).geocentricOutlineShadow()
                        .font(.system(size: 11, design: .monospaced))
                        .foregroundStyle(.secondary)
                        .frame(maxWidth: .infinity, alignment: .leading)
                        .padding(10)
                }
                .frame(height: 118)
                .background(Color.black.opacity(0.04))
                .clipShape(RoundedRectangle(cornerRadius: 7))
            }
        }
        .cardStyle()
    }
}

struct InstalledModelsCard: View {
    @EnvironmentObject private var ollama: OllamaManager
    @State private var query = ""

    private var filteredModels: [OllamaModel] {
        let trimmed = query.trimmingCharacters(in: .whitespacesAndNewlines).lowercased()
        guard !trimmed.isEmpty else { return ollama.installedModels }
        return ollama.installedModels.filter {
            $0.displayName.lowercased().contains(trimmed)
                || $0.name.lowercased().contains(trimmed)
                || $0.detailLine.lowercased().contains(trimmed)
        }
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            HStack {
                Text("Downloaded Models").geocentricOutlineShadow()
                    .font(.system(size: 16, weight: .semibold))
                Spacer()
                if !ollama.installedModels.isEmpty {
                    Text("\(ollama.installedModels.count)")
                        .font(.system(size: 11, weight: .bold, design: .monospaced))
                        .foregroundStyle(.secondary)
                        .padding(.horizontal, 7)
                        .padding(.vertical, 3)
                        .background(Color.black.opacity(0.05))
                        .clipShape(Capsule())
                }
            }

            if ollama.installedModels.isEmpty {
                Text("No local Ollama models yet. Download one below to start using Geocentric.").geocentricOutlineShadow()
                    .font(.system(size: 13))
                    .foregroundStyle(.secondary)
                    .padding(.vertical, 10)
            } else {
                HStack(spacing: 7) {
                    Image(systemName: "magnifyingglass")
                        .font(.system(size: 11, weight: .semibold))
                        .foregroundStyle(.secondary)
                    TextField("Filter downloaded models", text: $query)
                        .textFieldStyle(.plain)
                        .font(.system(size: 12))
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
                .frame(height: 30)
                .background(Color.black.opacity(0.045))
                .clipShape(RoundedRectangle(cornerRadius: 6))

                LazyVStack(spacing: 0) {
                    if filteredModels.isEmpty {
                        Text("No models match your filter.").geocentricOutlineShadow()
                            .font(.system(size: 13))
                            .foregroundStyle(.secondary)
                            .frame(maxWidth: .infinity, alignment: .leading)
                            .padding(.vertical, 12)
                    } else {
                        ForEach(filteredModels) { model in
                            InstalledModelRow(model: model)
                                .environmentObject(ollama)
                            if model.id != filteredModels.last?.id {
                                Divider()
                            }
                        }
                    }
                }
            }
        }
        .cardStyle()
    }
}

struct SuggestedModelsCard: View {
    @EnvironmentObject private var ollama: OllamaManager
    @State private var customModelID = ""

    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            Text("Download Models").geocentricOutlineShadow()
                .font(.system(size: 16, weight: .semibold))

            ForEach(ollama.suggestedModels) { model in
                HStack(spacing: 12) {
                    Text(model.badge).geocentricOutlineShadow()
                        .font(.system(size: 11, weight: .semibold))
                        .padding(.horizontal, 8)
                        .padding(.vertical, 4)
                        .background(Color.geocentricAccent.opacity(0.12))
                        .clipShape(RoundedRectangle(cornerRadius: 6))
                    VStack(alignment: .leading, spacing: 3) {
                        Text(model.name).geocentricOutlineShadow()
                            .font(.system(size: 14, weight: .semibold))
                        Text(model.description).geocentricOutlineShadow()
                            .font(.system(size: 12))
                            .foregroundStyle(.secondary)
                    }
                    Spacer()
                    let installedModel = ollama.installedModels.first { $0.matches(model.id) }
                    let installed = installedModel != nil
                    if installed {
                        Button(installedModel?.matches(ollama.selectedModel) == true ? "Selected" : "Use") {
                            ollama.selectModel(installedModel?.name ?? model.id)
                        }
                    } else {
                        Button(ollama.pullingModel == model.id ? "Downloading..." : "Download") {
                            ollama.downloadModel(model.id)
                        }
                        .disabled(ollama.pullingModel != nil || !ollama.isReady)
                    }
                }
                .padding(.vertical, 8)
                if model.id != ollama.suggestedModels.last?.id {
                    Divider()
                }
            }

            Divider()

            HStack(spacing: 10) {
                Image(systemName: "terminal")
                    .foregroundStyle(.secondary)
                TextField("Custom Ollama model, e.g. mistral:7b", text: $customModelID)
                    .textFieldStyle(.roundedBorder)
                    .onSubmit(downloadCustomModel)
                Button("Download") {
                    downloadCustomModel()
                }
                .disabled(customModelID.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty || ollama.pullingModel != nil || ollama.deletingModel != nil || !ollama.isReady)
            }
            .font(.system(size: 13))
        }
        .cardStyle()
    }

    private func downloadCustomModel() {
        let modelID = customModelID.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !modelID.isEmpty else { return }
        ollama.downloadModel(modelID)
        customModelID = ""
    }
}

private struct InstalledModelRow: View {
    @EnvironmentObject private var ollama: OllamaManager
    let model: OllamaModel

    private var selected: Bool {
        model.matches(ollama.selectedModel)
    }

    var body: some View {
        HStack(spacing: 12) {
            Image(systemName: selected ? "checkmark.circle.fill" : "cube.box")
                .foregroundStyle(selected ? Color.green : Color.secondary)
                .frame(width: 18)
            VStack(alignment: .leading, spacing: 3) {
                Text(model.displayName).geocentricOutlineShadow()
                    .font(.system(size: 14, weight: .semibold))
                    .lineLimit(1)
                if !model.detailLine.isEmpty {
                    Text(model.detailLine).geocentricOutlineShadow()
                        .font(.system(size: 12))
                        .foregroundStyle(.secondary)
                        .lineLimit(1)
                }
            }
            Spacer()
            if ollama.deletingModel == model.name {
                ProgressView()
                    .controlSize(.small)
            } else if selected {
                Label("Selected", systemImage: "checkmark.circle.fill").geocentricOutlineShadow()
                    .font(.system(size: 12, weight: .semibold))
                    .foregroundStyle(.green)
            } else {
                Button("Use") {
                    ollama.selectModel(model.name)
                }
            }

            Button(role: .destructive) {
                confirmDeleteModel(model)
            } label: {
                Image(systemName: "trash")
                    .foregroundStyle(.red.opacity(0.8))
            }
            .buttonStyle(.plain)
            .help("Delete Model")
            .disabled(ollama.pullingModel != nil || ollama.deletingModel != nil)
        }
        .padding(.vertical, 8)
        .contextMenu {
            Button("Copy Model Name") {
                NSPasteboard.general.clearContents()
                NSPasteboard.general.setString(model.name, forType: .string)
            }
            if !selected {
                Button("Use Model") {
                    ollama.selectModel(model.name)
                }
            }
            Button("Delete Model", role: .destructive) {
                confirmDeleteModel(model)
            }
        }
    }

    private func confirmDeleteModel(_ model: OllamaModel) {
        let alert = NSAlert()
        alert.messageText = "Delete \(model.displayName)?"
        alert.informativeText = "This removes the local Ollama model from disk. You can download it again later."
        alert.alertStyle = .warning
        alert.addButton(withTitle: "Delete")
        alert.addButton(withTitle: "Cancel")
        guard alert.runModal() == .alertFirstButtonReturn else { return }
        ollama.deleteModel(model.name)
    }
}

struct ModelsPageView: View {
    @EnvironmentObject private var appModel: NativeAppModel

    var body: some View {
        VStack(spacing: 18) {
            ModelManagerSheet(showsDone: false)
                .frame(maxWidth: 860, maxHeight: 640)
        }
        .padding(40)
    }
}

struct HistoryView: View {
    @EnvironmentObject private var appModel: NativeAppModel

    var body: some View {
        let conversations = Array(appModel.recentConversations.enumerated())

        ScrollView {
            VStack(alignment: .leading, spacing: 16) {
                HStack {
                    Text("Conversation History").geocentricOutlineShadow()
                        .font(.system(size: 26, weight: .semibold))
                        .foregroundStyle(.primary)
                    Spacer()
                    Button {
                        appModel.newConversation()
                    } label: {
                        Label("New", systemImage: "square.and.pencil").geocentricOutlineShadow()
                    }
                    .buttonStyle(.borderless)
                }
                
                if conversations.isEmpty {
                    Text("No conversation history.").geocentricOutlineShadow()
                        .font(.system(size: 14))
                        .foregroundStyle(.secondary)
                        .padding(.top, 8)
                } else {
                    ForEach(conversations, id: \.offset) { _, conversation in
                        HStack {
                            Button {
                                appModel.selectConversation(conversation.id)
                            } label: {
                                VStack(alignment: .leading, spacing: 4) {
                                    Text(conversation.title).geocentricOutlineShadow()
                                        .font(.system(size: 15, weight: .semibold))
                                        .foregroundStyle(.primary)
                                        .lineLimit(1)
                                    Text(conversation.project).geocentricOutlineShadow()
                                        .font(.system(size: 12))
                                        .foregroundStyle(.secondary)
                                        .lineLimit(1)
                                    Text(conversation.updatedAt, style: .relative).geocentricOutlineShadow()
                                        .font(.system(size: 11))
                                        .foregroundStyle(.tertiary)
                                }
                                .frame(maxWidth: .infinity, alignment: .leading)
                            }
                            .buttonStyle(.plain)
                            .pointerHover()
                            
                            Spacer()

                            Button {
                                appModel.exportConversation(conversation)
                            } label: {
                                Image(systemName: "square.and.arrow.up").geocentricOutlineShadow()
                                    .foregroundStyle(.secondary)
                            }
                            .buttonStyle(.plain)
                            .help("Export Thread")
                            .pointerHover()
                            
                            Button {
                                appModel.deleteConversation(conversation.id)
                            } label: {
                                Image(systemName: "trash").geocentricOutlineShadow()
                                    .foregroundStyle(.red.opacity(0.8))
                            }
                            .buttonStyle(.plain)
                            .pointerHover()
                        }
                        .padding(14)
                        .background(Color.primary.opacity(0.02))
                        .background(.ultraThinMaterial)
                        .clipShape(RoundedRectangle(cornerRadius: 8))
                        .overlay {
                            RoundedRectangle(cornerRadius: 8)
                                .stroke(Color.primary.opacity(0.08), lineWidth: 0.5)
                        }
                    }
                }
            }
            .padding(42)
            .frame(maxWidth: 800)
            .frame(maxWidth: .infinity, alignment: .leading)
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity)
    }
}

struct ScheduledTasksView: View {
    @EnvironmentObject private var server: DesktopServer
    @EnvironmentObject private var ollama: OllamaManager
    @State private var jobs: [ScheduledTask] = []
    @State private var name = ""
    @State private var prompt = ""
    @State private var hours = 0
    @State private var minutes = 30
    @State private var loading = false
    @State private var errorText = ""
    private let api = NativeAPIClient()

    var body: some View {
        VStack(alignment: .leading, spacing: 18) {
            HStack {
                VStack(alignment: .leading, spacing: 4) {
                    Text("Scheduled Tasks").geocentricOutlineShadow()
                        .font(.system(size: 26, weight: .semibold))
                    Text("Run recurring local agent prompts through the active service.").geocentricOutlineShadow()
                        .font(.system(size: 13))
                        .foregroundStyle(.secondary)
                }
                Spacer()
                if loading { ProgressView().controlSize(.small) }
                Button("Refresh") { loadJobs() }
                    .disabled(!server.isReady || loading)
            }

            if !server.isReady {
                VStack(alignment: .leading, spacing: 10) {
                    Text("Agent service is required for scheduled tasks.").geocentricOutlineShadow()
                        .font(.system(size: 15, weight: .semibold))
                    Text(server.statusText).geocentricOutlineShadow()
                        .font(.system(size: 13))
                        .foregroundStyle(.secondary)
                    Button("Restart Agent Service") { server.restart() }
                }
                .cardStyle()
            } else {
                VStack(alignment: .leading, spacing: 12) {
                    Text("New Task").geocentricOutlineShadow()
                        .font(.system(size: 16, weight: .semibold))
                    TextField("Task name", text: $name)
                        .textFieldStyle(.roundedBorder)
                    TextEditor(text: $prompt)
                        .font(.system(size: 13))
                        .frame(height: 82)
                        .scrollContentBackground(.hidden)
                        .padding(8)
                        .background(Color.black.opacity(0.035))
                        .clipShape(RoundedRectangle(cornerRadius: 7))
                    HStack {
                        Stepper("Every \(hours)h \(minutes)m", value: $minutes, in: 1...59)
                            .frame(maxWidth: 180)
                        Stepper("Hours \(hours)", value: $hours, in: 0...168)
                            .frame(maxWidth: 150)
                        Spacer()
                        Button("Create Task") { createJob() }
                            .disabled(name.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty || prompt.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty || loading)
                    }
                }
                .cardStyle()

                if !errorText.isEmpty {
                    Text(errorText).geocentricOutlineShadow()
                        .font(.system(size: 13, weight: .medium))
                        .foregroundStyle(.red)
                }

                ScrollView {
                    VStack(spacing: 10) {
                        if jobs.isEmpty {
                            Text("No scheduled tasks yet.").geocentricOutlineShadow()
                                .font(.system(size: 14))
                                .foregroundStyle(.secondary)
                                .frame(maxWidth: .infinity, alignment: .leading)
                                .padding(16)
                                .background(Color.white.opacity(0.62))
                                .clipShape(RoundedRectangle(cornerRadius: 8))
                        } else {
                            ForEach(jobs) { job in
                                HStack(alignment: .top, spacing: 12) {
                                    Image(systemName: "clock").geocentricOutlineShadow()
                                        .foregroundStyle(.secondary)
                                    VStack(alignment: .leading, spacing: 4) {
                                        Text(job.name).geocentricOutlineShadow()
                                            .font(.system(size: 15, weight: .semibold))
                                        Text(job.prompt).geocentricOutlineShadow()
                                            .font(.system(size: 13))
                                            .foregroundStyle(.secondary)
                                            .lineLimit(2)
                                        Text("Every \(job.interval_hours)h \(job.interval_minutes)m • \(formatModelName(job.model ?? ollama.selectedModel))").geocentricOutlineShadow()
                                            .font(.system(size: 12))
                                            .foregroundStyle(.tertiary)
                                    }
                                    Spacer()
                                    Button {
                                        deleteJob(job)
                                    } label: {
                                        Image(systemName: "trash").geocentricOutlineShadow()
                                    }
                                    .buttonStyle(.plain)
                                    .foregroundStyle(.secondary)
                                }
                                .padding(14)
                                .background(Color.white.opacity(0.62))
                                .clipShape(RoundedRectangle(cornerRadius: 8))
                            }
                        }
                    }
                }
            }
            Spacer()
        }
        .padding(42)
        .onAppear { loadJobs() }
    }

    private func loadJobs() {
        guard server.isReady, let baseURL = server.localURL else { return }
        loading = true
        errorText = ""
        Task {
            do {
                let loaded = try await api.listCronJobs(baseURL: baseURL)
                DispatchQueue.main.async {
                    jobs = loaded
                    loading = false
                }
            } catch {
                DispatchQueue.main.async {
                    errorText = error.localizedDescription
                    loading = false
                }
            }
        }
    }

    private func createJob() {
        guard server.isReady, let baseURL = server.localURL else { return }
        loading = true
        errorText = ""
        let selectedModel = ollama.selectedModel.isEmpty ? "llama3.2" : ollama.selectedModel
        Task {
            do {
                try await api.createCronJob(
                    baseURL: baseURL,
                    name: name.trimmingCharacters(in: .whitespacesAndNewlines),
                    prompt: prompt.trimmingCharacters(in: .whitespacesAndNewlines),
                    hours: hours,
                    minutes: max(1, minutes),
                    model: selectedModel
                )
                DispatchQueue.main.async {
                    name = ""
                    prompt = ""
                    loading = false
                    loadJobs()
                }
            } catch {
                DispatchQueue.main.async {
                    errorText = error.localizedDescription
                    loading = false
                }
            }
        }
    }

    private func deleteJob(_ job: ScheduledTask) {
        guard server.isReady, let baseURL = server.localURL else { return }
        loading = true
        errorText = ""
        Task {
            do {
                try await api.deleteCronJob(baseURL: baseURL, id: job.id)
                DispatchQueue.main.async {
                    jobs.removeAll { $0.id == job.id }
                    loading = false
                }
            } catch {
                DispatchQueue.main.async {
                    errorText = error.localizedDescription
                    loading = false
                }
            }
        }
    }
}
