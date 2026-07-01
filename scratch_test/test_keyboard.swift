import SwiftUI

struct TestKeyboardView: View {
    @State private var text = ""
    var body: some View {
        TextField("Enter text", text: $text, axis: .vertical)
            .onKeyPress(keys: [.return]) { press in
                if press.modifiers.contains(.shift) {
                    return .ignored
                } else {
                    print("Send prompt")
                    return .handled
                }
            }
            .frame(width: 300, height: 200)
    }
}
