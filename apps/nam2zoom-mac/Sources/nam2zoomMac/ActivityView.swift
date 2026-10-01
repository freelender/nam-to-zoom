import SwiftUI

struct ActivityView: View {
    @ObservedObject var vm: AppViewModel

    var body: some View {
        VStack(alignment: .leading, spacing: 6) {
            HStack {
                Text("Activity").font(.headline)
                Text(vm.status).foregroundStyle(.secondary)
                Spacer()
                Button("Clear log") { vm.log = "" }
                Button("Cancel build") { vm.cancelBuild() }
                    .disabled(!vm.canCancel)
            }

            if vm.busy {
                if vm.determinateProgress {
                    ProgressView(value: vm.progressValue)
                } else {
                    ProgressView().progressViewStyle(.linear)
                }
            } else {
                ProgressView(value: 0).opacity(0.15)
            }

            ScrollViewReader { proxy in
                ScrollView {
                    Text(vm.log.isEmpty ? " " : vm.log)
                        .font(.system(.caption, design: .monospaced))
                        .frame(maxWidth: .infinity, alignment: .leading)
                        .textSelection(.enabled)
                        .id("log-end")
                        .padding(6)
                }
                .background(Color.black.opacity(0.85))
                .onChange(of: vm.log) {
                    proxy.scrollTo("log-end", anchor: .bottom)
                }
            }
        }
        .padding(12)
    }
}
