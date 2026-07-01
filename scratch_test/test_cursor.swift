import SwiftUI
import AppKit

struct TestCursorView: View {
    var body: some View {
        VStack {
            Button("Hover Me") {
                print("Clicked")
            }
            .onHover { hovering in
                if hovering {
                    NSCursor.pointingHand.push()
                } else {
                    NSCursor.pop()
                }
            }
        }
        .frame(width: 300, height: 200)
    }
}
