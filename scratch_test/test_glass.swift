import SwiftUI

struct TestGlassView: View {
    var body: some View {
        VStack {
            Text("Testing Native Materials")
                .padding()
                .background(.ultraThinMaterial, in: RoundedRectangle(cornerRadius: 12))
        }
        .frame(width: 300, height: 200)
    }
}
