import SwiftUI
import UniformTypeIdentifiers

struct ConversationView: View {
    @EnvironmentObject private var appModel: NativeAppModel

    var body: some View {
        VStack(spacing: 0) {
            if let conversation = appModel.selectedConversation, !conversation.messages.isEmpty {
                MessagesList(messages: conversation.messages)
            } else {
                EmptyComposerStage()
            }

            if appModel.isSending || !appModel.activeAgentProgress.isEmpty || !appModel.activeAgentChanges.isEmpty {
                AgentActivityPanel()
                    .padding(.horizontal, 28)
                    .padding(.bottom, 10)
                    .transition(.move(edge: .bottom).combined(with: .opacity))
            }

            Composer()
                .padding(.horizontal, 28)
                .padding(.bottom, 24)
        }
    }
}

struct AgentActivityPanel: View {
    @EnvironmentObject private var appModel: NativeAppModel

    private var roadmapLines: [String] {
        appModel.activeAgentRoadmap
            .components(separatedBy: .newlines)
            .map { $0.trimmingCharacters(in: .whitespacesAndNewlines) }
            .filter { !$0.isEmpty }
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            HStack(spacing: 10) {
                if appModel.isSending {
                    PulsingIndicatorLight(color: .green)
                } else {
                    Circle()
                        .fill(Color.secondary.opacity(0.5))
                        .frame(width: 8, height: 8)
                }
                
                Text(appModel.activeAgentProgress.isEmpty ? appModel.statusText : appModel.activeAgentProgress).geocentricOutlineShadow()
                    .font(.system(size: 13, weight: .semibold))
                    .foregroundStyle(.primary)
                    .lineLimit(1)
                
                Spacer()
                
                if appModel.isSending {
                    Button {
                        appModel.stopResponse()
                    } label: {
                        HStack(spacing: 4) {
                            Image(systemName: "stop.fill").geocentricOutlineShadow()
                                .font(.system(size: 9, weight: .bold))
                            Text("Stop").geocentricOutlineShadow()
                                .font(.system(size: 11, weight: .semibold))
                        }
                        .padding(.horizontal, 10)
                        .padding(.vertical, 5)
                        .background(Color.red.opacity(0.15))
                        .foregroundStyle(.red)
                        .clipShape(Capsule())
                        .overlay {
                            Capsule().stroke(Color.red.opacity(0.3), lineWidth: 1)
                        }
                    }
                    .buttonStyle(.plain)
                    .hoverShadow(radius: 4)
                }
            }

            if !roadmapLines.isEmpty {
                VStack(alignment: .leading, spacing: 6) {
                    ForEach(Array(roadmapLines.prefix(5).enumerated()), id: \.offset) { _, line in
                        AgentRoadmapLineView(line: line)
                    }
                }
                .padding(10)
                .frame(maxWidth: .infinity, alignment: .leading)
                .background(Color.black.opacity(0.04))
                .clipShape(RoundedRectangle(cornerRadius: 10))
            }

            if !appModel.activeAgentChanges.isEmpty {
                ScrollView(.horizontal, showsIndicators: false) {
                    HStack(spacing: 8) {
                        ForEach(appModel.activeAgentChanges.prefix(8)) { change in
                            HStack(spacing: 6) {
                                Image(systemName: "doc.text").geocentricOutlineShadow()
                                    .font(.system(size: 10))
                                    .foregroundStyle(.secondary)
                                Text(change.path).geocentricOutlineShadow()
                                    .font(.system(size: 11.5, design: .monospaced))
                                    .lineLimit(1)
                                    .truncationMode(.middle)
                                    .frame(maxWidth: 180)
                                Text("+\(change.additions)").geocentricOutlineShadow()
                                    .foregroundStyle(.green)
                                Text("-\(change.deletions)").geocentricOutlineShadow()
                                    .foregroundStyle(.red)
                            }
                            .font(.system(size: 11, weight: .semibold))
                            .padding(.horizontal, 10)
                            .padding(.vertical, 6)
                            .liquidGlassCapsule()
                        }
                    }
                    .padding(.vertical, 4)
                }
            }
        }
        .padding(12)
        .frame(maxWidth: 760)
        .liquidGlass(cornerRadius: 16)
    }
}

struct EmptyComposerStage: View {
    @EnvironmentObject private var appModel: NativeAppModel

    var body: some View {
        ScrollView(.vertical, showsIndicators: false) {
            VStack(spacing: 24) {
                Spacer()
                    .frame(height: 36)
                
                VStack(spacing: 14) {
                    AppMark(size: 72)
                        .shadow(color: Color.black.opacity(0.08), radius: 10, y: 4)
                    
                    Text(appModel.selectedProject == nil ? "Welcome to Geocentric" : "Ready to Build").geocentricOutlineShadow()
                        .font(.system(size: 28, weight: .bold))
                        .foregroundStyle(.primary)
                    
                    Text("Ask questions, generate files, and run tasks with local developer agents.").geocentricOutlineShadow()
                        .font(.system(size: 14))
                        .foregroundStyle(.secondary)
                        .multilineTextAlignment(.center)
                        .frame(maxWidth: 420)
                }
                .padding(.bottom, 6)

                Button {
                    appModel.chooseProject(createConversationAfterSelection: false)
                } label: {
                    HStack(spacing: 14) {
                        Image(systemName: "folder.badge.gearshape").geocentricOutlineShadow()
                            .font(.system(size: 22))
                            .foregroundStyle(Color.geocentricAccent)
                            .frame(width: 48, height: 48)
                            .background(Color.geocentricAccent.opacity(0.12))
                            .clipShape(RoundedRectangle(cornerRadius: 8))
                        
                        VStack(alignment: .leading, spacing: 4) {
                            Text(appModel.selectedProject?.name ?? "Choose Project Folder").geocentricOutlineShadow()
                                .font(.system(size: 15, weight: .semibold))
                                .foregroundStyle(.primary)
                            Text(appModel.selectedProject == nil ? "Select a workspace directory to start" : "Change selected workspace directory").geocentricOutlineShadow()
                                .font(.system(size: 12))
                                .foregroundStyle(.secondary)
                        }
                        
                        Spacer()
                        
                        Image(systemName: "chevron.up.chevron.down").geocentricOutlineShadow()
                            .font(.system(size: 12, weight: .bold))
                            .foregroundStyle(.secondary)
                    }
                    .padding(16)
                    .frame(width: 380)
                    .liquidGlass(cornerRadius: 12)
                }
                .buttonStyle(.plain)

                if let project = appModel.selectedProject {
                    VStack(alignment: .leading, spacing: 12) {
                        Text("Project Launchpad")
                            .font(.system(size: 13, weight: .bold))
                            .foregroundStyle(.secondary)
                            .padding(.horizontal, 4)
                        
                        Grid(horizontalSpacing: 14, verticalSpacing: 14) {
                            GridRow {
                                Button {
                                    appModel.playSound("Pop")
                                    appModel.newConversation()
                                } label: {
                                    VStack(alignment: .leading, spacing: 6) {
                                        Image(systemName: "plus.bubble.fill")
                                            .font(.system(size: 18))
                                            .foregroundStyle(Color.geocentricAccent)
                                        Text("New Thread")
                                            .font(.system(size: 13, weight: .semibold))
                                            .foregroundStyle(.primary)
                                        Text("Start a new conversation thread")
                                            .font(.system(size: 11))
                                            .foregroundStyle(.secondary)
                                            .lineLimit(1)
                                    }
                                    .padding(12)
                                    .frame(maxWidth: .infinity, alignment: .leading)
                                    .liquidGlass(cornerRadius: 8)
                                }
                                .buttonStyle(.plain)
                                .pointerHover()
                                
                                Button {
                                    appModel.playSound("Pop")
                                    if appModel.selectedConversationID == nil {
                                        appModel.newConversation()
                                    }
                                    appModel.prompt = "Analyze this project workspace. Summarize what it does, what languages/dependencies it uses, and outline the codebase structure."
                                    appModel.sendPrompt()
                                } label: {
                                    VStack(alignment: .leading, spacing: 6) {
                                        Image(systemName: "chart.bar.doc.horizontal")
                                            .font(.system(size: 18))
                                            .foregroundStyle(Color.geocentricAccent)
                                        Text("Analyze Project")
                                            .font(.system(size: 13, weight: .semibold))
                                            .foregroundStyle(.primary)
                                        Text("Map structure & dependencies")
                                            .font(.system(size: 11))
                                            .foregroundStyle(.secondary)
                                            .lineLimit(1)
                                    }
                                    .padding(12)
                                    .frame(maxWidth: .infinity, alignment: .leading)
                                    .liquidGlass(cornerRadius: 8)
                                }
                                .buttonStyle(.plain)
                                .pointerHover()
                            }
                            
                            GridRow {
                                Button {
                                    appModel.playSound("Tink")
                                    NSWorkspace.shared.open(URL(fileURLWithPath: project.path))
                                } label: {
                                    VStack(alignment: .leading, spacing: 6) {
                                        Image(systemName: "finder.circle.fill")
                                            .font(.system(size: 18))
                                            .foregroundStyle(Color.geocentricAccent)
                                        Text("Open in Finder")
                                            .font(.system(size: 13, weight: .semibold))
                                            .foregroundStyle(.primary)
                                        Text("Reveal files in macOS Finder")
                                            .font(.system(size: 11))
                                            .foregroundStyle(.secondary)
                                            .lineLimit(1)
                                    }
                                    .padding(12)
                                    .frame(maxWidth: .infinity, alignment: .leading)
                                    .liquidGlass(cornerRadius: 8)
                                }
                                .buttonStyle(.plain)
                                .pointerHover()
                                
                                Button {
                                    appModel.playSound("Tink")
                                    let process = Process()
                                    process.executableURL = URL(fileURLWithPath: "/usr/bin/open")
                                    process.arguments = ["-a", "Terminal", project.path]
                                    try? process.run()
                                } label: {
                                    VStack(alignment: .leading, spacing: 6) {
                                        Image(systemName: "terminal.fill")
                                            .font(.system(size: 18))
                                            .foregroundStyle(Color.geocentricAccent)
                                        Text("Open Terminal")
                                            .font(.system(size: 13, weight: .semibold))
                                            .foregroundStyle(.primary)
                                        Text("Launch Terminal in workspace")
                                            .font(.system(size: 11))
                                            .foregroundStyle(.secondary)
                                            .lineLimit(1)
                                    }
                                    .padding(12)
                                    .frame(maxWidth: .infinity, alignment: .leading)
                                    .liquidGlass(cornerRadius: 8)
                                }
                                .buttonStyle(.plain)
                                .pointerHover()
                            }
                        }
                        .frame(width: 380)
                    }
                    .padding(.top, 10)
                }

                VStack(alignment: .center, spacing: 6) {
                    Text("Workspace Performance")
                        .font(.system(size: 11, weight: .bold))
                        .foregroundStyle(.secondary)
                    
                    HStack(spacing: 12) {
                        MiniMetricIndicator(name: "CPU", value: appModel.telemetry.cpuPercent, icon: "cpu", tintColor: .blue)
                        MiniMetricIndicator(name: "RAM", value: appModel.telemetry.memoryPercent, icon: "memorychip", tintColor: .purple)
                        if let gpu = appModel.telemetry.gpuPercent {
                            MiniMetricIndicator(name: "GPU", value: gpu, icon: "sparkles", tintColor: .orange)
                        }
                    }
                }
                .padding(.top, 16)

                Spacer()
                    .frame(height: 36)
            }
            .frame(maxWidth: .infinity)
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity)
    }
}

struct MessagesList: View {
    @EnvironmentObject private var appModel: NativeAppModel
    let messages: [ConversationMessage]

    @State private var autoScroll = true

    var body: some View {
        ScrollViewReader { proxy in
            ScrollView {
                LazyVStack(alignment: .leading, spacing: 18) {
                    ForEach(messages) { message in
                        MessageBubble(message: message)
                            .id(message.id)
                    }
                }
                .padding(.top, 82)
                .padding(.horizontal, 62)
                .padding(.bottom, 24)
                .frame(maxWidth: 980)
                .frame(maxWidth: .infinity)
            }
            .simultaneousGesture(
                DragGesture().onChanged { _ in
                    autoScroll = false
                }
            )
            .onChange(of: messages.count) { _, _ in
                autoScroll = true
                if let last = messages.last {
                    withAnimation(.easeOut(duration: 0.2)) {
                        proxy.scrollTo(last.id, anchor: .bottom)
                    }
                }
            }
            .onChange(of: messages.last?.content) { _, _ in
                if let last = messages.last, autoScroll {
                    proxy.scrollTo(last.id, anchor: .bottom)
                }
            }
            .onChange(of: appModel.activeAgentProgress) { _, _ in
                if let last = messages.last, autoScroll {
                    proxy.scrollTo(last.id, anchor: .bottom)
                }
            }
            .onChange(of: appModel.activeAgentChanges.count) { _, _ in
                if let last = messages.last, autoScroll {
                    proxy.scrollTo(last.id, anchor: .bottom)
                }
            }
            .onChange(of: appModel.isSending) { _, isSending in
                if isSending {
                    autoScroll = true
                }
                if let last = messages.last, autoScroll {
                    withAnimation(.easeOut(duration: 0.2)) {
                        proxy.scrollTo(last.id, anchor: .bottom)
                    }
                }
            }
        }
    }
}

struct MessageBubble: View {
    let message: ConversationMessage
    @EnvironmentObject private var appModel: NativeAppModel
    @State private var isHovering = false

    var body: some View {
        HStack(alignment: .top, spacing: 16) {
            if message.role == .assistant {
                AppMark(size: 32)
                    .shadow(color: Color.black.opacity(0.06), radius: 4, y: 2)
            } else {
                Image(systemName: "person.crop.circle.fill").geocentricOutlineShadow()
                    .font(.system(size: 32))
                    .foregroundStyle(.secondary)
            }

            VStack(alignment: .leading, spacing: 8) {
                HStack {
                    Text(message.role == .assistant ? "Geocentric" : "You").geocentricOutlineShadow()
                        .font(.system(size: 13, weight: .semibold))
                        .foregroundStyle(.primary)
                    
                    Spacer()
                    
                    if isHovering {
                        MessageHoverToolbar(message: message)
                            .transition(.opacity.combined(with: .scale(scale: 0.95)))
                    }
                }
                
                RenderedMessageContent(rawText: message.content)
            }
        }
        .padding(.horizontal, 20)
        .padding(.vertical, 16)
        .background(
            ZStack {
                if message.role == .assistant {
                    Color.primary.opacity(0.02)
                }
            }
        )
        .background(.ultraThinMaterial)
        .clipShape(RoundedRectangle(cornerRadius: 12))
        .overlay {
            RoundedRectangle(cornerRadius: 12)
                .stroke(Color.primary.opacity(0.08), lineWidth: 0.5)
        }
        .onHover { isHovering = $0 }
        .textSelection(.enabled)
    }
}

struct MessageHoverToolbar: View {
    let message: ConversationMessage
    @EnvironmentObject private var appModel: NativeAppModel

    var body: some View {
        HStack(spacing: 4) {
            Button {
                let pasteboard = NSPasteboard.general
                pasteboard.declareTypes([.string], owner: nil)
                pasteboard.setString(message.content, forType: .string)
                appModel.statusText = "Copied to clipboard"
            } label: {
                Image(systemName: "doc.on.doc").geocentricOutlineShadow()
                    .font(.system(size: 11))
                    .foregroundStyle(.primary)
                    .frame(width: 24, height: 24)
                    .background(Color.white.opacity(0.7))
                    .clipShape(RoundedRectangle(cornerRadius: 4))
                    .overlay {
                        RoundedRectangle(cornerRadius: 4)
                            .stroke(Color.primary.opacity(0.12), lineWidth: 1)
                    }
            }
            .buttonStyle(.plain)
            .help("Copy Text")
            .pointerHover()

            Button {
                appModel.prompt = message.content
                appModel.statusText = "Loaded message to composer"
            } label: {
                Image(systemName: "pencil").geocentricOutlineShadow()
                    .font(.system(size: 11))
                    .foregroundStyle(.primary)
                    .frame(width: 24, height: 24)
                    .background(Color.white.opacity(0.7))
                    .clipShape(RoundedRectangle(cornerRadius: 4))
                    .overlay {
                        RoundedRectangle(cornerRadius: 4)
                            .stroke(Color.primary.opacity(0.12), lineWidth: 1)
                    }
            }
            .buttonStyle(.plain)
            .help("Edit Prompt")
            .pointerHover()

            Button {
                deleteMessage()
            } label: {
                Image(systemName: "trash").geocentricOutlineShadow()
                    .font(.system(size: 11))
                    .foregroundStyle(.red)
                    .frame(width: 24, height: 24)
                    .background(Color.white.opacity(0.7))
                    .clipShape(RoundedRectangle(cornerRadius: 4))
                    .overlay {
                        RoundedRectangle(cornerRadius: 4)
                            .stroke(Color.red.opacity(0.24), lineWidth: 1)
                    }
            }
            .buttonStyle(.plain)
            .help("Delete Message")
            .pointerHover()
        }
        .padding(2)
        .background(.ultraThinMaterial)
        .clipShape(RoundedRectangle(cornerRadius: 6))
        .overlay {
            RoundedRectangle(cornerRadius: 6)
                .stroke(Color.primary.opacity(0.12), lineWidth: 0.5)
        }
    }

    private func deleteMessage() {
        guard let convID = appModel.selectedConversationID,
              let convIndex = appModel.conversations.firstIndex(where: { $0.id == convID })
        else { return }
        
        appModel.conversations[convIndex].messages.removeAll { $0.id == message.id }
        appModel.saveConversations()
        appModel.statusText = "Message deleted"
    }
}

struct MarkdownElement: Identifiable {
    let id = UUID()
    let isCode: Bool
    let language: String?
    let content: String
}

struct MarkdownBodyView: View {
    let bodyText: String

    var body: some View {
        let elements = parseMarkdown(bodyText)
        VStack(alignment: .leading, spacing: 12) {
            ForEach(elements) { element in
                if element.isCode {
                    CodeBlockView(language: element.language, code: element.content)
                } else {
                    MarkdownText(element.content)
                }
            }
        }
    }

    private func parseMarkdown(_ text: String) -> [MarkdownElement] {
        var elements: [MarkdownElement] = []
        let parts = text.components(separatedBy: "```")
        
        for (index, part) in parts.enumerated() {
            if index % 2 == 0 {
                if !part.isEmpty {
                    elements.append(MarkdownElement(isCode: false, language: nil, content: part))
                }
            } else {
                var language: String? = nil
                var code = part
                
                if let firstNewline = part.firstIndex(of: "\n") {
                    let langCandidate = String(part[..<firstNewline]).trimmingCharacters(in: .whitespacesAndNewlines)
                    if !langCandidate.isEmpty && langCandidate.count < 30 && !langCandidate.contains(" ") {
                        language = langCandidate
                        code = String(part[part.index(after: firstNewline)...])
                    }
                }
                
                elements.append(MarkdownElement(isCode: true, language: language, content: code))
            }
        }
        
        return elements
    }
}

struct CodeBlockView: View {
    let language: String?
    let code: String
    @EnvironmentObject private var appModel: NativeAppModel
    @State private var isCopied = false

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            HStack {
                Text(language?.uppercased() ?? "CODE").geocentricOutlineShadow()
                    .font(.system(size: 11, weight: .bold, design: .monospaced))
                    .foregroundStyle(.secondary)
                
                Spacer()
                
                HStack(spacing: 8) {
                    Button {
                        let pasteboard = NSPasteboard.general
                        pasteboard.declareTypes([.string], owner: nil)
                        pasteboard.setString(code, forType: .string)
                        appModel.statusText = "Code copied to clipboard"
                        appModel.playSound("Pop")
                        withAnimation {
                            isCopied = true
                        }
                        DispatchQueue.main.asyncAfter(deadline: .now() + 2.0) {
                            withAnimation {
                                isCopied = false
                            }
                        }
                    } label: {
                        HStack(spacing: 4) {
                            Image(systemName: isCopied ? "checkmark.circle.fill" : "doc.on.doc").geocentricOutlineShadow()
                            Text(isCopied ? "Copied!" : "Copy").geocentricOutlineShadow()
                        }
                        .font(.system(size: 11, weight: .semibold))
                        .foregroundStyle(isCopied ? .green : .secondary)
                        .padding(.horizontal, 8)
                        .padding(.vertical, 4)
                        .background(Color.white.opacity(0.06))
                        .clipShape(RoundedRectangle(cornerRadius: 4))
                    }
                    .buttonStyle(.plain)
                    .pointerHover()

                    Button {
                        runScript()
                    } label: {
                        HStack(spacing: 4) {
                            Image(systemName: "play.fill").geocentricOutlineShadow()
                            Text("Run").geocentricOutlineShadow()
                        }
                        .font(.system(size: 11, weight: .semibold))
                        .foregroundStyle(.white)
                        .padding(.horizontal, 8)
                        .padding(.vertical, 4)
                        .background(appModel.isSending ? Color.gray : Color.green)
                        .clipShape(RoundedRectangle(cornerRadius: 4))
                    }
                    .buttonStyle(.plain)
                    .disabled(appModel.isSending)
                    .pointerHover()
                }
            }
            .padding(.horizontal, 12)
            .padding(.vertical, 8)
            .background(Color.black.opacity(0.2))
            
            ScrollView(.horizontal, showsIndicators: true) {
                Text(code).geocentricOutlineShadow()
                    .font(.system(size: 13, design: .monospaced))
                    .foregroundStyle(Color(red: 0.9, green: 0.92, blue: 0.95))
                    .padding(14)
                    .textSelection(.enabled)
            }
        }
        .background(Color(red: 0.08, green: 0.09, blue: 0.12))
        .clipShape(RoundedRectangle(cornerRadius: 8))
        .overlay {
            RoundedRectangle(cornerRadius: 8)
                .stroke(Color.white.opacity(0.1), lineWidth: 0.5)
        }
        .padding(.vertical, 4)
    }

    private func runScript() {
        guard !appModel.isSending else { return }
        
        let scriptPrompt = """
Please run the following code block in the workspace:
```\(language ?? "")
\(code)
```
"""
        appModel.prompt = scriptPrompt
        appModel.sendPrompt()
    }
}

struct RenderedMessageContent: View {
    let rawText: String
    private var parsed: ParsedMessageContent { MessageContentParser.parse(rawText) }

    var body: some View {
        let content = parsed
        VStack(alignment: .leading, spacing: 10) {
            if !content.body.isEmpty {
                MarkdownBodyView(bodyText: content.body)
            }

            if !content.images.isEmpty {
                ImageGallery(urls: content.images)
            }

            if !content.thoughts.isEmpty {
                ShowAgentThinkingView(lines: content.thoughts)
            }

            if !content.references.isEmpty {
                CollapsibleInfoBlock(title: "References", icon: "link", lines: content.references)
            }

            if content.body.isEmpty && content.images.isEmpty && content.thoughts.isEmpty && content.references.isEmpty {
                Text("No displayable content.").geocentricOutlineShadow()
                    .font(.system(size: 14))
                    .foregroundStyle(.secondary)
            }
        }
    }
}

struct MarkdownText: View {
    let text: String

    init(_ text: String) {
        self.text = text
    }

    var body: some View {
        if let attributed = try? AttributedString(markdown: text, options: AttributedString.MarkdownParsingOptions(interpretedSyntax: .inlineOnlyPreservingWhitespace)) {
            Text(attributed).geocentricOutlineShadow()
                .font(.system(size: 14.5))
                .foregroundStyle(.primary)
                .textSelection(.enabled)
                .lineSpacing(4)
        } else {
            Text(text).geocentricOutlineShadow()
                .font(.system(size: 14.5))
                .foregroundStyle(.primary)
                .textSelection(.enabled)
                .lineSpacing(4)
        }
    }
}

struct ImageGallery: View {
    let urls: [URL]

    private var columns: [GridItem] {
        [GridItem(.adaptive(minimum: 132, maximum: 180), spacing: 10)]
    }

    var body: some View {
        LazyVGrid(columns: columns, alignment: .leading, spacing: 10) {
            ForEach(urls, id: \.absoluteString) { url in
                AsyncImage(url: url) { phase in
                    switch phase {
                    case .empty:
                        RoundedRectangle(cornerRadius: 8)
                            .fill(Color.black.opacity(0.04))
                            .overlay { ProgressView().controlSize(.small) }
                    case .success(let image):
                        image
                            .resizable()
                            .scaledToFill()
                    case .failure:
                        ImagePlaceholder(url: url)
                    @unknown default:
                        ImagePlaceholder(url: url)
                    }
                }
                .frame(height: 132)
                .clipShape(RoundedRectangle(cornerRadius: 8))
                .overlay {
                    RoundedRectangle(cornerRadius: 8)
                        .stroke(Color.black.opacity(0.08), lineWidth: 1)
                }
            }
        }
        .frame(maxWidth: 600)
    }
}

struct ImagePlaceholder: View {
    let url: URL

    var body: some View {
        VStack(spacing: 8) {
            Image(systemName: "photo").geocentricOutlineShadow()
                .font(.system(size: 22))
                .foregroundStyle(.secondary)
            Text(url.host ?? "Image unavailable").geocentricOutlineShadow()
                .font(.system(size: 11, weight: .medium))
                .foregroundStyle(.secondary)
                .lineLimit(1)
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity)
        .background(Color.black.opacity(0.035))
    }
}

struct CollapsibleInfoBlock: View {
    let title: String
    let icon: String
    let lines: [String]
    @State private var expanded = false

    var body: some View {
        DisclosureGroup(isExpanded: $expanded) {
            VStack(alignment: .leading, spacing: 7) {
                ForEach(Array(lines.enumerated()), id: \.offset) { _, line in
                    Text(line).geocentricOutlineShadow()
                        .font(.system(size: 12, design: .monospaced))
                        .foregroundStyle(.secondary)
                        .textSelection(.enabled)
                }
            }
            .padding(.top, 8)
        } label: {
            VStack(alignment: .leading, spacing: 4) {
                HStack {
                    Label("\(title) (\(lines.count))", systemImage: icon).geocentricOutlineShadow()
                        .font(.system(size: 12, weight: .semibold))
                        .foregroundStyle(.secondary)
                    Spacer()
                }
            }
        }
        .padding(10)
        .background(Color.black.opacity(0.035))
        .clipShape(RoundedRectangle(cornerRadius: 8))
    }
}

struct ShowAgentThinkingView: View {
    let lines: [String]
    @State private var expanded = false
    @State private var animatePulse = false
    @EnvironmentObject private var appModel: NativeAppModel
    
    var lastTwoSentences: String {
        let fullText = lines.joined(separator: " ")
        let sentences = fullText.components(separatedBy: CharacterSet(charactersIn: ".!?"))
            .map { $0.trimmingCharacters(in: .whitespacesAndNewlines) }
            .filter { !$0.isEmpty }
        
        let suffix = sentences.suffix(2)
        if suffix.isEmpty { return "" }
        return suffix.joined(separator: ". ") + "."
    }
    
    var body: some View {
        VStack(alignment: .leading, spacing: 4) {
            Button {
                withAnimation(.spring(response: 0.3, dampingFraction: 0.7)) {
                    expanded.toggle()
                    appModel.playSound("Tink")
                }
            } label: {
                HStack(spacing: 8) {
                    Image(systemName: "brain.head.profile").geocentricOutlineShadow()
                        .font(.system(size: 14, weight: .bold))
                        .foregroundStyle(Color.geocentricAccent)
                        .rotationEffect(.degrees(animatePulse ? 15 : -15))
                        .scaleEffect(animatePulse ? 1.15 : 0.85)
                        .onAppear {
                            withAnimation(.easeInOut(duration: 1.5).repeatForever(autoreverses: true)) {
                                animatePulse = true
                            }
                        }
                    
                    Text("Show Agent Thinking").geocentricOutlineShadow()
                        .font(.system(size: 12, weight: .bold))
                        .foregroundStyle(.secondary)
                    
                    Spacer()
                    
                    Image(systemName: expanded ? "chevron.up" : "chevron.down").geocentricOutlineShadow()
                        .font(.system(size: 10, weight: .bold))
                        .foregroundStyle(.secondary)
                }
                .padding(.horizontal, 10)
                .padding(.vertical, 8)
                .background(Color.black.opacity(0.04))
                .cornerRadius(6)
            }
            .buttonStyle(.plain)
            
            if expanded {
                VStack(alignment: .leading, spacing: 0) {
                    HStack {
                        VStack(alignment: .leading) {
                            Text(lastTwoSentences)
                                .font(.system(size: 12.5, weight: .medium, design: .monospaced))
                                .foregroundStyle(Color.white.opacity(0.85))
                                .padding(12)
                                .frame(maxWidth: .infinity, alignment: .leading)
                                .transition(.asymmetric(
                                    insertion: .move(edge: .bottom).combined(with: .opacity),
                                    removal: .move(edge: .top).combined(with: .opacity)
                                ))
                                .id(lastTwoSentences)
                        }
                    }
                    .background(
                        RoundedRectangle(cornerRadius: 8)
                            .fill(Color.black.opacity(0.65))
                            .overlay(
                                RoundedRectangle(cornerRadius: 8)
                                    .strokeBorder(Color.white.opacity(0.12), lineWidth: 1)
                            )
                    )
                    .shadow(color: Color.black.opacity(0.18), radius: 6, x: 0, y: 3)
                    .padding(.top, 4)
                }
            }
        }
        .padding(6)
        .background(Color.white.opacity(0.02))
        .cornerRadius(10)
    }
}

struct ParsedMessageContent {
    var body: String
    var images: [URL]
    var references: [String]
    var thoughts: [String]
}

enum MessageContentParser {
    static func parse(_ raw: String) -> ParsedMessageContent {
        var working = raw.replacingOccurrences(of: "\r\n", with: "\n")
        var images: [URL] = []
        var references: [String] = []
        var thoughts: [String] = []

        extractBlocks(tag: "images", from: &working).forEach { block in
            images.append(contentsOf: urls(in: block).filter { isLikelyImageURL($0) })
            let nonImages = urls(in: block).filter { !isLikelyImageURL($0) }.map(\.absoluteString)
            references.append(contentsOf: nonImages)
        }

        let tags = [
            "think", "thought", "status", "search", "image_search", "browse_url", "run_command", "run_file", 
            "read_file", "port_check", "http_request", "write_file", "edit_file", 
            "delete_file", "install_package", "agent_terminal", "run_bg_command", 
            "check_process", "capture_view", "view_project_tree", "system_info", 
            "list_processes", "list_directory", "stat_path", "make_directory",
            "copy_file", "move_file", "download_url", "update_roadmap", "replace_file_content",
            "multi_replace_file_content", "ask_permission", "define_subagent", 
            "invoke_subagent", "manage_subagents", "manage_task"
        ]

        for tag in tags {
            extractBlocks(tag: tag, from: &working).forEach { block in
                let clean = stripTags(block).trimmingCharacters(in: .whitespacesAndNewlines)
                if !clean.isEmpty {
                    let summary = clean.count > 300 ? String(clean.prefix(300)) + "..." : clean
                    thoughts.append(summary)
                }
            }
        }

        var bodyLines: [String] = []
        for line in working.components(separatedBy: .newlines) {
            let trimmed = line.trimmingCharacters(in: .whitespacesAndNewlines)
            let lineURLs = urls(in: trimmed)
            if lineURLs.count == 1, trimmed == lineURLs[0].absoluteString {
                if isLikelyImageURL(lineURLs[0]) {
                    images.append(lineURLs[0])
                } else {
                    references.append(lineURLs[0].absoluteString)
                }
            } else if trimmed.hasPrefix("<") && trimmed.hasSuffix(">") {
                let clean = stripTags(trimmed).trimmingCharacters(in: .whitespacesAndNewlines)
                if !clean.isEmpty {
                    thoughts.append(clean)
                }
            } else {
                bodyLines.append(line)
            }
        }

        var body = bodyLines.joined(separator: "\n")
        
        // Strip any remaining general dangling opening/closing tags at the end of the text
        let generalPartialPattern = "<[a-zA-Z_]*\\b[^>]*$"
        if let regex = try? NSRegularExpression(pattern: generalPartialPattern) {
            let nsText = body as NSString
            body = regex.stringByReplacingMatches(in: body, range: NSRange(location: 0, length: nsText.length), withTemplate: "")
        }
        let generalClosingPartialPattern = "<\\/[a-zA-Z_]*[^>]*$"
        if let regex = try? NSRegularExpression(pattern: generalClosingPartialPattern) {
            let nsText = body as NSString
            body = regex.stringByReplacingMatches(in: body, range: NSRange(location: 0, length: nsText.length), withTemplate: "")
        }

        body = stripDanglingToolSyntax(body).trimmingCharacters(in: .whitespacesAndNewlines)

        return ParsedMessageContent(
            body: body,
            images: uniqueURLs(images),
            references: uniqueStrings(references),
            thoughts: uniqueStrings(thoughts)
        )
    }

    private static func extractBlocks(tag: String, from text: inout String) -> [String] {
        var blocks: [String] = []
        
        // 1. Closed tags
        let closedPattern = "<\(tag)\\b[^>]*>([\\s\\S]*?)</\(tag)>"
        if let regex = try? NSRegularExpression(pattern: closedPattern, options: [.caseInsensitive]) {
            let nsText = text as NSString
            let matches = regex.matches(in: text, range: NSRange(location: 0, length: nsText.length))
            for match in matches {
                if match.numberOfRanges > 1 {
                    blocks.append(nsText.substring(with: match.range(at: 1)))
                }
            }
            text = regex.stringByReplacingMatches(in: text, range: NSRange(location: 0, length: nsText.length), withTemplate: "")
        }
        
        // 2. Unclosed/dangling tags (e.g., during streaming)
        let openPattern = "<\(tag)\\b[^>]*>([\\s\\S]*?)$"
        if let regex = try? NSRegularExpression(pattern: openPattern, options: [.caseInsensitive]) {
            let nsText = text as NSString
            let matches = regex.matches(in: text, range: NSRange(location: 0, length: nsText.length))
            for match in matches {
                if match.numberOfRanges > 1 {
                    blocks.append(nsText.substring(with: match.range(at: 1)))
                }
            }
            text = regex.stringByReplacingMatches(in: text, range: NSRange(location: 0, length: nsText.length), withTemplate: "")
        }

        // 3. Partial tags at the very end of string (e.g. "<write_file" or "<write_f")
        let partialPattern = "<\\/?\(tag)\\b[^>]*$"
        if let regex = try? NSRegularExpression(pattern: partialPattern, options: [.caseInsensitive]) {
            let nsText = text as NSString
            text = regex.stringByReplacingMatches(in: text, range: NSRange(location: 0, length: nsText.length), withTemplate: "")
        }
        
        return blocks
    }

    private static func urls(in text: String) -> [URL] {
        let pattern = #"https?://[^\s<>"')\]]+"#
        guard let regex = try? NSRegularExpression(pattern: pattern) else { return [] }
        let nsText = text as NSString
        return regex.matches(in: text, range: NSRange(location: 0, length: nsText.length)).compactMap {
            URL(string: nsText.substring(with: $0.range))
        }
    }

    private static func stripTags(_ text: String) -> String {
        text.replacingOccurrences(of: #"<[^>]+>"#, with: " ", options: .regularExpression)
    }

    private static func stripDanglingToolSyntax(_ text: String) -> String {
        text
            .replacingOccurrences(of: #"(?im)^\s*\[(?:image|web|search|tool|status)[^\]\n]{0,80}\]\s*:?\s*"#, with: "", options: .regularExpression)
            .replacingOccurrences(of: #"\n{3,}"#, with: "\n\n", options: .regularExpression)
    }

    private static func isLikelyImageURL(_ url: URL) -> Bool {
        let lower = url.path.lowercased()
        return [".png", ".jpg", ".jpeg", ".webp", ".gif"].contains { lower.hasSuffix($0) }
    }

    private static func uniqueURLs(_ urls: [URL]) -> [URL] {
        var seen = Set<String>()
        return urls.filter { seen.insert($0.absoluteString).inserted }
    }

    private static func uniqueStrings(_ lines: [String]) -> [String] {
        var seen = Set<String>()
        return lines
            .map { $0.trimmingCharacters(in: .whitespacesAndNewlines) }
            .filter { !$0.isEmpty && seen.insert($0).inserted }
    }
}

struct Composer: View {
    @EnvironmentObject private var appModel: NativeAppModel
    @EnvironmentObject private var ollama: OllamaManager
    @EnvironmentObject private var server: DesktopServer
    @FocusState private var focused: Bool
    @State private var isDropTargeted = false

    private var editorHeight: CGFloat {
        let text = appModel.prompt.isEmpty ? "" : appModel.prompt
        let visualLines = max(1, text.components(separatedBy: .newlines).count)
        let softWrapEstimate = max(0, text.count / 76)
        let lines = min(6, max(1, visualLines + softWrapEstimate))
        return CGFloat(lines * 22 + 28)
    }

    var body: some View {
        let hasText = !appModel.prompt.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
        let canSend = hasText && !appModel.isSending
        VStack(spacing: 0) {
            if !appModel.pendingAttachments.isEmpty || !appModel.stagedContextFiles.isEmpty {
                ScrollView(.horizontal, showsIndicators: false) {
                    HStack(spacing: 8) {
                        ForEach(appModel.pendingAttachments) { attachment in
                            AttachmentChip(attachment: attachment) {
                                appModel.removeAttachment(attachment)
                            }
                        }
                        ForEach(appModel.stagedContextFiles) { file in
                            StagedContextChip(file: file) {
                                appModel.removeStagedContextFile(file)
                            }
                        }
                    }
                    .padding(.horizontal, 14)
                    .padding(.top, 12)
                }
            }

            ZStack(alignment: .topLeading) {
                TextField("Ask anything, @ to mention, / for actions", text: $appModel.prompt, axis: .vertical)
                    .focused($focused)
                    .font(.system(size: 15))
                    .textFieldStyle(.plain)
                    .lineLimit(1...6)
                    .frame(height: editorHeight)
                    .padding(.horizontal, 16)
                    .padding(.top, 10)
                    .padding(.bottom, 4)
                    .onKeyPress(keys: [.return]) { press in
                        if press.modifiers.contains(.shift) || press.modifiers.contains(.option) {
                            return .ignored
                        } else {
                            if canSend {
                                appModel.sendPrompt()
                            }
                            return .handled
                        }
                    }
            }

            HStack(spacing: 12) {
                Button {
                    appModel.chooseAttachments()
                } label: {
                    Image(systemName: "plus")
                        .font(.system(size: 14, weight: .medium))
                        .foregroundStyle(.primary)
                        .frame(width: 28, height: 28)
                        .background(Color.white.opacity(0.68))
                        .clipShape(RoundedRectangle(cornerRadius: 6))
                        .overlay {
                            RoundedRectangle(cornerRadius: 6)
                                .stroke(Color.primary.opacity(0.12), lineWidth: 1)
                        }
                        .contentShape(Rectangle())
                        .hoverShadow()
                }
                .buttonStyle(.plain)
                .help("Attach files")
                .pointerHover()

                Button {
                    appModel.chooseStagedContextFiles()
                } label: {
                    Image(systemName: "pin")
                        .font(.system(size: 13, weight: .medium))
                        .foregroundStyle(.primary)
                        .frame(width: 28, height: 28)
                        .background(Color.white.opacity(0.68))
                        .clipShape(RoundedRectangle(cornerRadius: 6))
                        .overlay {
                            RoundedRectangle(cornerRadius: 6)
                                .stroke(Color.primary.opacity(0.12), lineWidth: 1)
                        }
                        .contentShape(Rectangle())
                        .hoverShadow()
                }
                .buttonStyle(.plain)
                .help("Pin files into active context")
                .pointerHover()

                Menu {
                    Button {
                        appModel.playSound("Pop")
                        appModel.prompt = "Please perform a detailed code review of this code for security issues, runtime performance, design patterns, and readability:\n\n"
                    } label: {
                        Label("Code Review", systemImage: "doc.text.magnifyingglass")
                    }
                    
                    Button {
                        appModel.playSound("Pop")
                        appModel.prompt = "Explain how this code works in simple terms, detailing each key function and variable:\n\n"
                    } label: {
                        Label("Explain Code", systemImage: "lightbulb")
                    }
                    
                    Button {
                        appModel.playSound("Pop")
                        appModel.prompt = "Create comprehensive unit tests with edge cases and mock data for this code:\n\n"
                    } label: {
                        Label("Generate Unit Tests", systemImage: "checkmark.seal")
                    }
                    
                    Button {
                        appModel.playSound("Pop")
                        appModel.prompt = "Refactor this code to follow best practices, improve time/space complexity, and make it cleaner:\n\n"
                    } label: {
                        Label("Refactor & Optimize", systemImage: "arrow.triangle.2.circlepath")
                    }
                    
                    Button {
                        appModel.playSound("Pop")
                        appModel.prompt = "Analyze this code to locate potential bugs, logic flaws, memory leaks, or race conditions, and suggest fixes:\n\n"
                    } label: {
                        Label("Find & Fix Bugs", systemImage: "ladybug")
                    }
                } label: {
                    Image(systemName: "doc.text.magnifyingglass")
                        .font(.system(size: 13, weight: .medium))
                        .foregroundStyle(.primary)
                        .frame(width: 28, height: 28)
                        .background(Color.white.opacity(0.68))
                        .clipShape(RoundedRectangle(cornerRadius: 6))
                        .overlay {
                            RoundedRectangle(cornerRadius: 6)
                                .stroke(Color.primary.opacity(0.12), lineWidth: 1)
                        }
                        .contentShape(Rectangle())
                        .hoverShadow()
                }
                .menuStyle(.borderlessButton)
                .frame(width: 28, height: 28)
                .help("Insert prompt templates")
                .pointerHover()

                Toggle(isOn: $appModel.agentMode) {
                    Label("Agent", systemImage: "hammer")
                }
                .toggleStyle(.checkbox)
                .font(.system(size: 12))
                .foregroundStyle(.primary)
                .hoverShadow(radius: 5)
                .help("Use the local agent service for app/workspace tasks")
                .pointerHover()

                Toggle(isOn: $appModel.webSearch) {
                    Label("Web", systemImage: "magnifyingglass")
                }
                .toggleStyle(.checkbox)
                .font(.system(size: 12))
                .foregroundStyle(.primary)
                .disabled(!appModel.agentMode)
                .opacity(appModel.agentMode ? 1 : 0.45)
                .hoverShadow(radius: 5)
                .help("Allow the agent service to use web/search tools when the prompt asks for them.")
                .pointerHover()

                Spacer()

                Text(server.mode == .localWiFi ? "Wi-Fi" : "Local")
                    .font(.system(size: 12, weight: .medium))
                    .foregroundStyle(.secondary)

                Button {
                    if appModel.isSending {
                        appModel.stopResponse()
                    } else {
                        appModel.sendPrompt()
                    }
                } label: {
                    Image(systemName: appModel.isSending ? "stop.fill" : "arrow.up")
                        .font(.system(size: 14, weight: .semibold))
                        .foregroundStyle(Color.white)
                        .frame(width: 32, height: 32)
                        .background(appModel.isSending ? Color.red : (canSend ? Color.geocentricAccent : Color.gray.opacity(0.45)))
                        .clipShape(Circle())
                        .hoverShadow()
                }
                .buttonStyle(.plain)
                .pointerHover()
                .disabled(!canSend && !appModel.isSending)
            }
            .padding(.horizontal, 14)
            .padding(.bottom, 12)

            HStack {
                StatusDot(text: appModel.statusText)
                Spacer()
                if !ollama.statusText.isEmpty {
                    Text(ollama.statusText)
                        .font(.system(size: 11))
                        .foregroundStyle(.tertiary)
                        .lineLimit(1)
                }
            }
            .padding(.horizontal, 16)
            .padding(.bottom, 10)
        }
        .liquidGlass(cornerRadius: 16)
        .overlay {
            RoundedRectangle(cornerRadius: 16)
                .stroke(isDropTargeted ? Color.geocentricAccent : Color.clear, lineWidth: 2)
        }
        .frame(maxWidth: 760)
        .onAppear { focused = true }
        .onDrop(of: [UTType.fileURL.identifier], isTargeted: $isDropTargeted, perform: handleFileDrop)
        .onChange(of: appModel.agentMode) { _, enabled in
            if !enabled {
                appModel.webSearch = false
            }
        }
    }

    private func handleFileDrop(providers: [NSItemProvider]) -> Bool {
        var accepted = false
        for provider in providers where provider.hasItemConformingToTypeIdentifier(UTType.fileURL.identifier) {
            accepted = true
            provider.loadItem(forTypeIdentifier: UTType.fileURL.identifier, options: nil) { item, _ in
                let url: URL?
                if let data = item as? Data {
                    url = URL(dataRepresentation: data, relativeTo: nil)
                } else {
                    url = item as? URL
                }

                guard let url else { return }
                DispatchQueue.main.async {
                    appModel.attachFiles(urls: [url])
                }
            }
        }
        return accepted
    }
}

struct AttachmentChip: View {
    let attachment: LocalAttachment
    let remove: () -> Void

    var body: some View {
        HStack(spacing: 7) {
            Image(systemName: attachment.mime.hasPrefix("image/") ? "photo" : "doc.text")
                .font(.system(size: 12, weight: .medium))
            Text(attachment.name)
                .font(.system(size: 12, weight: .medium))
                .lineLimit(1)
                .truncationMode(.middle)
                .frame(maxWidth: 180)
            Button(action: remove) {
                Image(systemName: "xmark")
                    .font(.system(size: 9, weight: .bold))
            }
            .buttonStyle(.plain)
        }
        .padding(.horizontal, 10)
        .padding(.vertical, 6)
        .background(Color.black.opacity(0.055))
        .clipShape(RoundedRectangle(cornerRadius: 7))
    }
}

struct StagedContextChip: View {
    let file: StagedContextFile
    let remove: () -> Void

    var body: some View {
        HStack(spacing: 7) {
            Image(systemName: "pin.fill")
                .font(.system(size: 11, weight: .medium))
                .foregroundStyle(Color.geocentricAccent)
            VStack(alignment: .leading, spacing: 1) {
                Text(file.name)
                    .font(.system(size: 12, weight: .semibold))
                    .lineLimit(1)
                Text(file.path)
                    .font(.system(size: 10))
                    .foregroundStyle(.secondary)
                    .lineLimit(1)
                    .truncationMode(.middle)
            }
            .frame(maxWidth: 190, alignment: .leading)
            Button(action: remove) {
                Image(systemName: "xmark")
                    .font(.system(size: 9, weight: .bold))
            }
            .buttonStyle(.plain)
        }
        .padding(.horizontal, 10)
        .padding(.vertical, 6)
        .background(Color.geocentricAccent.opacity(0.10))
        .clipShape(RoundedRectangle(cornerRadius: 7))
    }
}

struct MiniMetricIndicator: View {
    let name: String
    let value: Double
    let icon: String
    let tintColor: Color

    var body: some View {
        HStack(spacing: 8) {
            Image(systemName: icon).geocentricOutlineShadow()
                .font(.system(size: 12))
                .foregroundStyle(tintColor)
            
            VStack(alignment: .leading, spacing: 1) {
                Text(name).font(.system(size: 9, weight: .semibold)).foregroundStyle(.secondary)
                Text("\(Int(value))%").font(.system(size: 11, weight: .bold, design: .monospaced)).foregroundStyle(.primary)
            }
        }
        .padding(.horizontal, 10)
        .padding(.vertical, 6)
        .background(Color.white.opacity(0.04))
        .clipShape(RoundedRectangle(cornerRadius: 6))
        .overlay {
            RoundedRectangle(cornerRadius: 6)
                .stroke(Color.primary.opacity(0.08), lineWidth: 1)
        }
    }
}
