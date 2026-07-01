import SwiftUI
import AppKit
import WebKit

func formatModelName(_ model: String) -> String {
    model
        .replacingOccurrences(of: ":latest", with: "")
        .split(separator: "-")
        .map { $0.capitalized }
        .joined(separator: " ")
}

struct StatusChip: View {
    let text: String
    let icon: String
    let tint: Color

    var body: some View {
        HStack(spacing: 6) {
            Image(systemName: icon).geocentricOutlineShadow()
                .font(.system(size: 10, weight: .semibold))
            Text(text).geocentricOutlineShadow()
                .font(.system(size: 11, weight: .semibold))
        }
        .foregroundStyle(tint)
        .padding(.horizontal, 9)
        .padding(.vertical, 5)
        .background(tint.opacity(0.12))
        .clipShape(RoundedRectangle(cornerRadius: 7))
    }
}

struct StatusDot: View {
    let text: String

    var body: some View {
        HStack(spacing: 6) {
            Circle()
                .fill(Color.green)
                .frame(width: 6, height: 6)
            Text(text).geocentricOutlineShadow()
                .font(.system(size: 11))
                .foregroundStyle(.secondary)
                .lineLimit(1)
        }
    }
}

struct AppMark: View {
    let size: CGFloat

    var body: some View {
        if let image = NSImage(named: "appicon") ?? NSApplication.shared.applicationIconImage {
            Image(nsImage: image)
                .resizable()
                .aspectRatio(contentMode: .fit)
                .frame(width: size, height: size)
                .clipShape(RoundedRectangle(cornerRadius: min(8, size / 8)))
                .geocentricOutlineShadow()
        } else {
            RoundedRectangle(cornerRadius: min(8, size / 8))
                .fill(Color.accentColor.opacity(0.18))
                .frame(width: size, height: size)
                .overlay(Text("G").geocentricOutlineShadow().font(.system(size: size * 0.42, weight: .bold)))
        }
    }
}

struct VisualEffectView: NSViewRepresentable {
    var material: NSVisualEffectView.Material
    var blendingMode: NSVisualEffectView.BlendingMode

    func makeNSView(context: Context) -> NSVisualEffectView {
        let view = NSVisualEffectView()
        view.material = material
        view.blendingMode = blendingMode
        view.state = .active
        view.isEmphasized = true
        return view
    }

    func updateNSView(_ view: NSVisualEffectView, context: Context) {
        view.material = material
        view.blendingMode = blendingMode
        view.state = .active
        view.isEmphasized = true
    }
}

extension Color {
    static let geocentricCanvas = Color(red: 0.965, green: 0.967, blue: 0.972)
    static let geocentricSidebar = Color(red: 0.925, green: 0.932, blue: 0.944)

    static var geocentricAccent: Color {
        guard let model = NativeAppModel.sharedReference else {
            return Color.accentColor
        }
        switch model.customAccentColor {
        case "emerald": return Color(red: 0.1, green: 0.65, blue: 0.35)
        case "sunset": return Color(red: 0.95, green: 0.45, blue: 0.15)
        case "violet": return Color(red: 0.55, green: 0.25, blue: 0.85)
        case "crimson": return Color(red: 0.85, green: 0.15, blue: 0.25)
        default: return Color(red: 0.1, green: 0.45, blue: 0.9)
        }
    }
}

struct PointerHoverModifier: ViewModifier {
    @State private var active = false
    func body(content: Content) -> some View {
        content
            .contentShape(Rectangle())
            .onHover { inside in
                if inside {
                    NSCursor.pointingHand.push()
                    active = true
                } else if active {
                    NSCursor.pop()
                    active = false
                }
            }
            .onDisappear {
                if active {
                    NSCursor.pop()
                    active = false
                }
            }
    }
}

extension View {
    func pointerHover() -> some View {
        self.modifier(PointerHoverModifier())
    }

    func cardStyle() -> some View {
        self
            .padding(16)
            .liquidGlass(cornerRadius: 12)
    }

    func liquidGlass(cornerRadius: CGFloat = 16) -> some View {
        self.modifier(LiquidGlassModifier(cornerRadius: cornerRadius))
    }

    func glassPanel(cornerRadius: CGFloat = 12) -> some View {
        self.modifier(GlassPanelModifier(cornerRadius: cornerRadius))
    }

    func hoverShadow(radius: CGFloat = 9) -> some View {
        modifier(HoverShadowModifier(radius: radius))
    }

    func liquidGlassCapsule() -> some View {
        self
            .background(
                LiquidGlassBackground(variant: .v11, cornerRadius: 20) {
                    Color.clear
                }
                .clipShape(Capsule())
            )
            .overlay {
                Capsule()
                    .strokeBorder(Color.black.opacity(0.24), lineWidth: 1.0)
            }
            .shadow(color: Color.black.opacity(0.03), radius: 3, x: 0, y: 1)
    }

    func geocentricOutlineShadow() -> some View {
        self.modifier(GeocentricTextAndIconStyle())
    }
}

struct LiquidGlassModifier: ViewModifier {
    let cornerRadius: CGFloat
    @Environment(\.colorScheme) private var colorScheme

    func body(content: Content) -> some View {
        content
            .background(
                LiquidGlassBackground(variant: .v11, cornerRadius: cornerRadius) {
                    if colorScheme == .dark {
                        Color.black.opacity(0.36)
                    } else {
                        Color.white.opacity(0.68)
                    }
                }
            )
            .overlay {
                RoundedRectangle(cornerRadius: cornerRadius)
                    .strokeBorder(
                        LinearGradient(
                            colors: [
                                colorScheme == .dark ? Color.black.opacity(0.28) : Color.white.opacity(0.4),
                                colorScheme == .dark ? Color.white.opacity(0.18) : Color.black.opacity(0.1)
                            ],
                            startPoint: .topLeading,
                            endPoint: .bottomTrailing
                        ),
                        lineWidth: 1.0
                    )
            }
            .shadow(color: colorScheme == .dark ? Color.black.opacity(0.06) : Color.black.opacity(0.03), radius: 10, x: 0, y: 5)
    }
}

struct GlassPanelModifier: ViewModifier {
    let cornerRadius: CGFloat
    @Environment(\.colorScheme) private var colorScheme

    func body(content: Content) -> some View {
        content
            .background(
                LiquidGlassBackground(variant: .v11, cornerRadius: cornerRadius) {
                    if colorScheme == .dark {
                        Color.black.opacity(0.36)
                    } else {
                        Color.white.opacity(0.68)
                    }
                }
            )
            .overlay {
                RoundedRectangle(cornerRadius: cornerRadius)
                    .strokeBorder(colorScheme == .dark ? Color.black.opacity(0.24) : Color.white.opacity(0.5), lineWidth: 1.0)
            }
            .shadow(color: colorScheme == .dark ? Color.black.opacity(0.05) : Color.black.opacity(0.02), radius: 8, x: 0, y: 4)
    }
}

struct GeocentricTextAndIconStyle: ViewModifier {
    @Environment(\.colorScheme) private var colorScheme

    func body(content: Content) -> some View {
        if colorScheme == .dark {
            content
                .shadow(color: .black, radius: 0.35, x: 0, y: 0)
                .shadow(color: Color.black.opacity(0.35), radius: 1.5, x: 0.8, y: 1.0)
        } else {
            content
                .shadow(color: .white, radius: 0.35, x: 0, y: 0)
                .shadow(color: Color.white.opacity(0.65), radius: 1.5, x: 0.8, y: 1.0)
        }
    }
}

public enum GlassVariant: Int, CaseIterable, Identifiable, Sendable {
    case v0  = 0,  v1  = 1,  v2  = 2,  v3  = 3,  v4  = 4
    case v5  = 5,  v6  = 6,  v7  = 7,  v8  = 8,  v9  = 9
    case v10 = 10, v11 = 11, v12 = 12, v13 = 13, v14 = 14
    case v15 = 15, v16 = 16, v17 = 17, v18 = 18, v19 = 19

    public var id: Int { rawValue }
}

public struct LiquidGlassBackground<Content: View>: NSViewRepresentable {
    private let content: Content
    private let cornerRadius: CGFloat
    private let variant: GlassVariant

    public init(
        variant: GlassVariant = .v11,
        cornerRadius: CGFloat = 10,
        @ViewBuilder content: () -> Content
    ) {
        self.variant      = variant
        self.cornerRadius = cornerRadius
        self.content      = content()
    }

    @inline(__always)
    private func setterSelector(for key: String, privateVariant: Bool = true) -> Selector? {
        guard !key.isEmpty else { return nil }
        let name: String
        if privateVariant {
            let cleaned = key.hasPrefix("_") ? key : "_" + key
            name = "set" + cleaned
        } else {
            let first = String(key.prefix(1)).uppercased()
            let rest  = String(key.dropFirst())
            name = "set" + first + rest
        }
        return NSSelectorFromString(name + ":")
    }

    private typealias VariantSetterIMP = @convention(c) (AnyObject, Selector, Int) -> Void

    private func callPrivateVariantSetter(on object: AnyObject, value: Int) {
        guard
            let sel   = setterSelector(for: "variant", privateVariant: true),
            let m     = class_getInstanceMethod(object_getClass(object), sel)
        else {
            return
        }
        let imp = method_getImplementation(m)
        let f   = unsafeBitCast(imp, to: VariantSetterIMP.self)
        f(object, sel, value)
    }

    public func makeNSView(context: Context) -> NSView {
        if let glassType = NSClassFromString("NSGlassEffectView") as? NSView.Type {
            let glass = glassType.init(frame: .zero)
            glass.setValue(cornerRadius, forKey: "cornerRadius")
            callPrivateVariantSetter(on: glass, value: variant.rawValue)

            let hosting = NSHostingView(rootView: content)
            hosting.translatesAutoresizingMaskIntoConstraints = false
            glass.setValue(hosting, forKey: "contentView")
            return glass
        }

        let fallback = NSVisualEffectView()
        fallback.material = .underWindowBackground

        let hosting = NSHostingView(rootView: content)
        hosting.translatesAutoresizingMaskIntoConstraints = false
        fallback.addSubview(hosting)
        NSLayoutConstraint.activate([
            hosting.leadingAnchor.constraint(equalTo: fallback.leadingAnchor),
            hosting.trailingAnchor.constraint(equalTo: fallback.trailingAnchor),
            hosting.topAnchor.constraint(equalTo: fallback.topAnchor),
            hosting.bottomAnchor.constraint(equalTo: fallback.bottomAnchor)
        ])
        return fallback
    }

    public func updateNSView(_ nsView: NSView, context: Context) {
        if let hosting = nsView.value(forKey: "contentView") as? NSHostingView<Content> {
            hosting.rootView = content
        }
        nsView.setValue(cornerRadius, forKey: "cornerRadius")
        callPrivateVariantSetter(on: nsView, value: variant.rawValue)
    }
}

struct HoverShadowModifier: ViewModifier {
    let radius: CGFloat
    @State private var hovering = false

    func body(content: Content) -> some View {
        content
            .shadow(color: Color.black.opacity(hovering ? 0.14 : 0), radius: hovering ? radius : 0, x: 0, y: hovering ? 4 : 0)
            .scaleEffect(hovering ? 1.01 : 1)
            .animation(.easeOut(duration: 0.12), value: hovering)
            .onHover { hovering = $0 }
    }
}

struct PulsingIndicatorLight: View {
    @State private var isAnimating = false
    var color: Color = .green

    var body: some View {
        Circle()
            .fill(color)
            .frame(width: 8, height: 8)
            .shadow(color: color.opacity(0.8), radius: 4, x: 0, y: 0)
            .opacity(isAnimating ? 0.45 : 1.0)
            .animation(.easeInOut(duration: 0.8).repeatForever(autoreverses: true), value: isAnimating)
            .onAppear {
                isAnimating = true
            }
    }
}

struct PulsingIcon: View {
    let systemName: String
    let color: Color
    @State private var pulse = false

    var body: some View {
        Image(systemName: systemName).geocentricOutlineShadow()
            .font(.system(size: 11, weight: .bold))
            .foregroundStyle(color)
            .opacity(pulse ? 0.45 : 1.0)
            .animation(.easeInOut(duration: 0.6).repeatForever(autoreverses: true), value: pulse)
            .onAppear {
                pulse = true
            }
    }
}

struct AgentRoadmapLineView: View {
    let line: String

    var body: some View {
        let isDone = line.contains("[x]")
        let isInProgress = line.contains("[/]")
        let cleanText = line
            .replacingOccurrences(of: "- [x] ", with: "")
            .replacingOccurrences(of: "- [/] ", with: "")
            .replacingOccurrences(of: "- [ ] ", with: "")
            .replacingOccurrences(of: "- ", with: "")
        
        return HStack(spacing: 8) {
            if isDone {
                Image(systemName: "checkmark.circle.fill").geocentricOutlineShadow()
                    .font(.system(size: 11, weight: .bold))
                    .foregroundStyle(.green)
            } else if isInProgress {
                PulsingIcon(systemName: "arrow.triangle.2.circlepath", color: Color.accentColor)
            } else {
                Image(systemName: "circle").geocentricOutlineShadow()
                    .font(.system(size: 11))
                    .foregroundStyle(Color.secondary.opacity(0.6))
            }
            
            Text(cleanText).geocentricOutlineShadow()
                .font(.system(size: 12, weight: isInProgress ? .medium : .regular))
                .foregroundStyle(isDone ? Color.secondary : (isInProgress ? Color.primary : Color.secondary.opacity(0.8)))
                .lineLimit(1)
        }
    }
}

struct FlowingGradientView: View {
    @EnvironmentObject private var appModel: NativeAppModel

    var body: some View {
        WatercolorWebView(animated: appModel.animatedBackgroundEnabled)
            .ignoresSafeArea()
    }
}

class NonInteractiveWKWebView: WKWebView {
    override func hitTest(_ point: NSPoint) -> NSView? {
        return nil
    }
}

struct WatercolorWebView: NSViewRepresentable {
    let animated: Bool

    func makeNSView(context: Context) -> NonInteractiveWKWebView {
        let preferences = WKWebpagePreferences()
        preferences.allowsContentJavaScript = true
        
        let configuration = WKWebViewConfiguration()
        configuration.defaultWebpagePreferences = preferences
        configuration.setValue(false, forKey: "drawsBackground") // Allow transparency
        
        let webView = NonInteractiveWKWebView(frame: .zero, configuration: configuration)
        webView.setValue(false, forKey: "drawsBackground")
        
        let html = getHTMLContent(animated: animated)
        webView.loadHTMLString(html, baseURL: nil)
        return webView
    }
    
    func updateNSView(_ nsView: NonInteractiveWKWebView, context: Context) {
        let js = "setLooping(\(animated ? "true" : "false"));"
        nsView.evaluateJavaScript(js, completionHandler: nil)
    }
    
    private func getHTMLContent(animated: Bool) -> String {
        return """
        <!DOCTYPE html>
        <html>
        <head>
            <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no">
            <style>
                html, body {
                    width: 100%;
                    height: 100%;
                    margin: 0;
                    padding: 0;
                    overflow: hidden;
                    background-color: #f5f2eb;
                    user-select: none;
                    -webkit-user-select: none;
                    font-family: system-ui, -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
                    pointer-events: none !important;
                }
                #canvasContainer {
                    position: absolute;
                    top: 0;
                    left: 0;
                    width: 100%;
                    height: 100%;
                    z-index: 1;
                    overflow: hidden;
                    background-color: #f7f4ec;
                    pointer-events: none !important;
                }
                canvas {
                    display: block;
                    width: 100%;
                    height: 100%;
                    filter: blur(32px) saturate(1.45) contrast(1.06);
                    transform: scale(1.08);
                    transition: filter 0.3s ease;
                    pointer-events: none !important;
                }
                #paperOverlay {
                    position: absolute;
                    inset: 0;
                    z-index: 2;
                    pointer-events: none;
                    mix-blend-mode: multiply;
                    opacity: 0.22;
                    transition: opacity 0.3s ease;
                }
            </style>
        </head>
        <body>
            <div id="canvasContainer">
                <canvas id="watercolorCanvas"></canvas>
                <div id="paperOverlay"></div>
            </div>
            <script>
                // --- High-Performance HSL Watercolor Compensated Engine ---
                function hslToRgb(h, s, l) {
                    h = h % 360;
                    if (h < 0) h += 360;
                    s /= 100;
                    l /= 100;

                    let adjustedL = l;
                    if (h > 40 && h < 75) {
                        adjustedL = Math.min(0.92, l * 1.15);
                    } else if (h > 210 && h < 275) {
                        adjustedL = l * 0.88;
                    }

                    let c = (1 - Math.abs(2 * adjustedL - 1)) * s;
                    let x = c * (1 - Math.abs((h / 60) % 2 - 1));
                    let m = adjustedL - c / 2;
                    let r = 0, g = 0, b = 0;

                    if (0 <= h && h < 60) { r = c; g = x; b = 0; }
                    else if (60 <= h && h < 120) { r = x; g = c; b = 0; }
                    else if (120 <= h && h < 180) { r = 0; g = c; b = x; }
                    else if (180 <= h && h < 240) { r = 0; g = x; b = c; }
                    else if (240 <= h && h < 300) { r = x; g = 0; b = c; }
                    else if (300 <= h && h < 360) { r = c; g = 0; b = x; }

                    return {
                        r: Math.round((r + m) * 255),
                        g: Math.round((g + m) * 255),
                        b: Math.round((b + m) * 255)
                    };
                }

                let activeColorKey = 'cycle';
                let activeHueValue = 0;
                let flowSpeedMultiplier = 1.2;
                let colorMorphSpeed = 1.8;
                let wetEdgeIntensity = 1.8;
                let blurAmount = 32;
                let brushSize = 120;
                let blendMode = 'source-over';
                let paperOpacity = 0.22;
                let isFlowing = true;
                let isLooping = \(animated ? "true" : "false");

                const canvas = document.getElementById('watercolorCanvas');
                const ctx = canvas.getContext('2d', { willReadFrequently: true });

                let width, height;
                let baseLayers = [];
                let brushStrokes = [];
                let particles = [];
                let globalRainbowTime = 180;

                function initPaperTexture() {
                    const patternCanvas = document.createElement('canvas');
                    patternCanvas.width = 320;
                    patternCanvas.height = 320;
                    const pCtx = patternCanvas.getContext('2d');
                    
                    pCtx.fillStyle = '#fdfbf7';
                    pCtx.fillRect(0, 0, 320, 320);
                    
                    const imgData = pCtx.getImageData(0, 0, 320, 320);
                    const data = imgData.data;
                    
                    for (let i = 0; i < data.length; i += 4) {
                        const grain = (Math.random() - 0.5) * 13;
                        const x = (i / 4) % 320;
                        const y = Math.floor((i / 4) / 320);
                        const fiberX = Math.sin(x * 0.08) * Math.cos(y * 0.07) * 4;
                        const fiberY = Math.cos(x * 0.04) * Math.sin(y * 0.1) * 4;
                        const noise = grain + fiberX + fiberY;
                        
                        data[i] = Math.min(255, Math.max(0, data[i] + noise));
                        data[i+1] = Math.min(255, Math.max(0, data[i+1] + noise - 1));
                        data[i+2] = Math.min(255, Math.max(0, data[i+2] + noise - 4));
                    }
                    pCtx.putImageData(imgData, 0, 0);
                    
                    const paperUrl = patternCanvas.toDataURL();
                    document.getElementById('paperOverlay').style.backgroundImage = `url(${paperUrl})`;
                    document.getElementById('paperOverlay').style.opacity = paperOpacity;
                }

                class FlowingBrushStroke {
                    constructor(relX, relY, relRadius, hueOffsetFraction, isUserDrawn = false) {
                        this.relX = relX;
                        this.relY = relY;
                        this.relRadius = relRadius;
                        this.isUserDrawn = isUserDrawn;
                        this.hueOffsetFraction = hueOffsetFraction;
                        this.fadeIn = 0.0;
                        this.isAccent = !isUserDrawn && (Math.random() < 0.20);
                        this.hueOffsetRange = 40;
                        this.noiseOffset = Math.random() * 1000;
                        this.phase = Math.random() * Math.PI * 2;
                        this.aspectRatioX = 3.6 + Math.random() * 1.8;
                        this.aspectRatioY = 1.1 + Math.random() * 0.7;
                        
                        this.numSegments = 24;
                        this.bristleSpikesLeft = [];
                        this.bristleSpikesRight = [];
                        this.topWavyOffsets = [];
                        this.bottomWavyOffsets = [];
                        
                        for (let i = 0; i <= this.numSegments; i++) {
                            this.bristleSpikesLeft.push(0.5 + Math.random() * 0.5);
                            this.bristleSpikesRight.push(0.5 + Math.random() * 0.5);
                            this.topWavyOffsets.push((Math.random() - 0.5) * 0.15);
                            this.bottomWavyOffsets.push((Math.random() - 0.5) * 0.15);
                        }
                        
                        this.opacity = isUserDrawn ? 0.35 : 0.65;
                        this.lifetime = 1.0;
                        this.decay = isUserDrawn ? 0.0004 : 0.0;

                        this.updateDimensions();
                        this.updateColors();
                    }

                    updateDimensions() {
                        this.x = this.relX * width;
                        this.y = this.relY * height;
                        this.radius = this.relRadius * Math.min(width, height);
                        this.lengthX = this.radius * this.aspectRatioX;
                        this.heightY = this.radius * this.aspectRatioY;
                    }

                    updateColors() {
                        let strokeHue;
                        if (this.isUserDrawn) {
                            strokeHue = globalRainbowTime % 360;
                        } else {
                            const base = globalRainbowTime;
                            if (this.isAccent) {
                                strokeHue = (base + 180 + this.hueOffsetFraction * this.hueOffsetRange) % 360;
                            } else {
                                strokeHue = (base + this.hueOffsetFraction * this.hueOffsetRange) % 360;
                            }
                        }

                        const col1 = hslToRgb(strokeHue, 92, 72);
                        this.r1 = col1.r; this.g1 = col1.g; this.b1 = col1.b;

                        const col2 = hslToRgb(strokeHue + 15, 92, 72);
                        this.r2 = col2.r; this.g2 = col2.g; this.b2 = col2.b;

                        const colEdge = hslToRgb(strokeHue, 100, 50);
                        this.er = colEdge.r; this.eg = colEdge.g; this.eb = colEdge.b;
                    }

                    update() {
                        if (this.isUserDrawn) {
                            this.lifetime -= this.decay * flowSpeedMultiplier;
                        }
                        if (this.fadeIn < 1.0) {
                            this.fadeIn += 0.015 * flowSpeedMultiplier;
                            if (this.fadeIn > 1.0) this.fadeIn = 1.0;
                        }
                        if (isFlowing) {
                            this.phase += 0.0035 * flowSpeedMultiplier;
                            this.relX += (0.0016 + Math.sin(this.phase * 0.4) * 0.0005) * flowSpeedMultiplier;
                            this.relY += (Math.cos(this.phase * 0.25 + this.noiseOffset) * 0.0004) * flowSpeedMultiplier;

                            if (this.relX > 1.35) {
                                this.relX = -0.35;
                                this.relY = Math.random() * 0.9 + 0.05;
                                this.fadeIn = 0.0;
                                this.isAccent = (Math.random() < 0.20);
                            }
                        }
                        this.updateColors();
                        this.updateDimensions();
                    }

                    draw() {
                        if (this.lifetime <= 0) return;
                        ctx.save();
                        ctx.globalCompositeOperation = blendMode;
                        const currentAlpha = this.opacity * this.lifetime * this.fadeIn;

                        const grad = ctx.createLinearGradient(this.x - this.lengthX/2, this.y, this.x + this.lengthX/2, this.y);
                        grad.addColorStop(0, `rgba(${Math.round(this.r1)}, ${Math.round(this.g1)}, ${Math.round(this.b1)}, 0.0)`);
                        grad.addColorStop(0.2, `rgba(${Math.round(this.r1)}, ${Math.round(this.g1)}, ${Math.round(this.b1)}, ${currentAlpha * 0.92})`);
                        grad.addColorStop(0.8, `rgba(${Math.round(this.r2)}, ${Math.round(this.g2)}, ${Math.round(this.b2)}, ${currentAlpha * 0.92})`);
                        grad.addColorStop(1, `rgba(${Math.round(this.r2)}, ${Math.round(this.g2)}, ${Math.round(this.b2)}, 0.0)`);

                        // Draw bleed/background blob
                        ctx.beginPath();
                        ctx.ellipse(this.x, this.y, (this.lengthX * 1.22)/2, (this.heightY * 1.35)/2, 0, 0, Math.PI * 2);
                        ctx.fillStyle = `rgba(${Math.round((this.r1+this.r2)/2)}, ${Math.round((this.g1+this.g2)/2)}, ${Math.round((this.b1+this.b2)/2)}, ${currentAlpha * 0.16})`;
                        ctx.fill();

                        // Draw core blob
                        ctx.beginPath();
                        ctx.ellipse(this.x, this.y, this.lengthX/2, this.heightY/2, 0, 0, Math.PI * 2);
                        ctx.fillStyle = grad;
                        ctx.fill();

                        // Draw wet edge stroke
                        ctx.strokeStyle = `rgba(${Math.round(this.er)}, ${Math.round(this.eg)}, ${Math.round(this.eb)}, ${currentAlpha * 0.55 * wetEdgeIntensity})`;
                        ctx.lineWidth = 1.8;
                        ctx.beginPath();
                        ctx.ellipse(this.x, this.y, this.lengthX/2, this.heightY/2, 0, 0, Math.PI * 2);
                        ctx.stroke();
                        ctx.restore();
                    }
                }

                class FoundationRibbon {
                    constructor(laneY, hueOffsetFraction, amplitude, frequency) {
                        this.laneY = laneY;
                        this.hueOffsetFraction = hueOffsetFraction;
                        this.amplitude = amplitude;
                        this.frequency = frequency;
                        this.phase = Math.random() * Math.PI * 2;
                    }

                    update() {
                        if (isFlowing) {
                            this.phase += 0.003 * flowSpeedMultiplier;
                        }
                        const base = globalRainbowTime;
                        const spread = 35;
                        const ribbonHue = (base + this.hueOffsetFraction * spread) % 360;
                        const col = hslToRgb(ribbonHue, 85, 75);
                        this.r = col.r; this.g = col.g; this.b = col.b;
                    }

                    draw() {
                        ctx.save();
                        ctx.globalCompositeOperation = 'source-over';

                        const segments = 24;
                        const points = [];
                        const midY = this.laneY * height;
                        const waveHeight = this.amplitude * height;

                        for (let i = 0; i <= segments; i++) {
                            const ratio = i / segments;
                            const x = ratio * width;
                            const sineWarp = Math.sin(ratio * this.frequency + this.phase) * waveHeight;
                            const cosWarp = Math.cos(ratio * (this.frequency * 1.5) - this.phase * 0.7) * (waveHeight * 0.35);
                            points.push({ x, y: midY + sineWarp + cosWarp });
                        }

                        ctx.beginPath();
                        ctx.moveTo(0, height);
                        ctx.lineTo(points[0].x, points[0].y);
                        for (let i = 1; i < points.length; i++) {
                            ctx.lineTo(points[i].x, points[i].y);
                        }
                        ctx.lineTo(width, height);
                        ctx.closePath();

                        const grad = ctx.createLinearGradient(0, midY - waveHeight * 1.5, 0, midY + waveHeight * 1.5);
                        grad.addColorStop(0, `rgba(${Math.round(this.r)}, ${Math.round(this.g)}, ${Math.round(this.b)}, 0.0)`);
                        grad.addColorStop(0.5, `rgba(${Math.round(this.r)}, ${Math.round(this.g)}, ${Math.round(this.b)}, 0.38)`);
                        grad.addColorStop(1, `rgba(${Math.round(this.r)}, ${Math.round(this.g)}, ${Math.round(this.b)}, 0.0)`);

                        ctx.fillStyle = grad;
                        ctx.fill();
                        ctx.restore();
                    }
                }

                class PaintParticle {
                    constructor(x, y, hue) {
                        this.x = x;
                        this.y = y;
                        this.hue = hue;
                        this.vx = (Math.random() - 0.5) * 1.8;
                        this.vy = (Math.random() - 0.5) * 1.1;
                        this.size = Math.random() * 2.2 + 0.6;
                        this.alpha = Math.random() * 0.35 + 0.15;
                        this.life = 1.0;
                        this.decay = 0.005 + Math.random() * 0.01;
                    }

                    update() {
                        this.x += this.vx;
                        this.y += this.vy;
                        this.vx *= 0.98;
                        this.vy *= 0.98;
                        this.life -= this.decay * flowSpeedMultiplier;
                    }

                    draw() {
                        const pig = hslToRgb(this.hue, 95, 70);
                        ctx.fillStyle = `rgba(${pig.r}, ${pig.g}, ${pig.b}, ${this.alpha * this.life})`;
                        ctx.beginPath();
                        ctx.arc(this.x, this.y, this.size, 0, Math.PI * 2);
                        ctx.fill();
                    }
                }

                function loadPresetLayout() {
                    brushStrokes = [];
                    baseLayers = [];
                    particles = [];
                    
                    baseLayers.push(new FoundationRibbon(0.20, -0.6, 0.22, 3.5));
                    baseLayers.push(new FoundationRibbon(0.42, -0.3, 0.18, 4.2));
                    baseLayers.push(new FoundationRibbon(0.60,  0.0, 0.25, 3.0));
                    baseLayers.push(new FoundationRibbon(0.78,  0.3, 0.20, 5.0));
                    baseLayers.push(new FoundationRibbon(0.92,  0.6, 0.15, 4.0));

                    brushStrokes.push(new FlowingBrushStroke(0.04, 0.15, 0.28, -0.8));
                    brushStrokes.push(new FlowingBrushStroke(0.15, 0.45, 0.25, -0.5));
                    brushStrokes.push(new FlowingBrushStroke(0.28, 0.82, 0.30, -0.2));
                    brushStrokes.push(new FlowingBrushStroke(0.35, 0.22, 0.25,  0.1));
                    brushStrokes.push(new FlowingBrushStroke(0.48, 0.60, 0.28,  0.4));
                    brushStrokes.push(new FlowingBrushStroke(0.55, 0.40, 0.26,  0.7));
                    brushStrokes.push(new FlowingBrushStroke(0.68, 0.72, 0.24, -0.9));
                    brushStrokes.push(new FlowingBrushStroke(0.75, 0.28, 0.30, -0.6));
                    brushStrokes.push(new FlowingBrushStroke(0.85, 0.55, 0.26, -0.3));
                    brushStrokes.push(new FlowingBrushStroke(0.95, 0.35, 0.32,  0.0));
                    brushStrokes.push(new FlowingBrushStroke(0.90, 0.85, 0.25,  0.3));
                    brushStrokes.push(new FlowingBrushStroke(0.18, 0.30, 0.26,  0.6));
                    brushStrokes.push(new FlowingBrushStroke(0.40, 0.75, 0.25,  0.9));
                    brushStrokes.push(new FlowingBrushStroke(0.62, 0.12, 0.28, -0.7));
                    brushStrokes.push(new FlowingBrushStroke(0.80, 0.82, 0.30, -0.4));

                    brushStrokes.forEach(s => s.fadeIn = 1.0);
                }

                function renderScene() {
                    if (!isLooping) return;
                    ctx.fillStyle = '#fbf9f4';
                    ctx.fillRect(0, 0, width, height);

                    baseLayers.forEach(layer => {
                        layer.update();
                        layer.draw();
                    });

                    brushStrokes.forEach((stroke, idx) => {
                        stroke.update();
                        stroke.draw();
                        if (stroke.isUserDrawn && stroke.lifetime <= 0) {
                            brushStrokes.splice(idx, 1);
                        }
                    });

                    particles.forEach((part, idx) => {
                        part.update();
                        part.draw();
                        if (part.life <= 0) {
                            particles.splice(idx, 1);
                        }
                    });

                    globalRainbowTime += 0.08 * colorMorphSpeed * flowSpeedMultiplier;
                    requestAnimationFrame(renderScene);
                }

                function setLooping(active) {
                    if (isLooping === active) return;
                    isLooping = active;
                    if (isLooping) {
                        renderScene();
                    }
                }

                // Mouse/touch event listeners disabled for high performance

                function handleResize() {
                    width = canvas.width = Math.ceil(window.innerWidth / 4);
                    height = canvas.height = Math.ceil(window.innerHeight / 4);
                    brushStrokes.forEach(stroke => stroke.updateDimensions());
                }

                window.addEventListener('resize', handleResize);

                window.onload = function() {
                    handleResize();
                    initPaperTexture();
                    loadPresetLayout();
                    renderScene();
                };
            </script>
        </body>
        </html>
        """
    }
}
