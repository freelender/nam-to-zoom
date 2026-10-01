import Foundation
import AppKit
import Combine
import CryptoKit
import UniformTypeIdentifiers

struct SimpleError: LocalizedError {
    let message: String
    init(_ message: String) { self.message = message }
    var errorDescription: String? { message }
}

/// Thread-safe cancel flag: set from the main-actor Cancel button, polled
/// from the non-isolated `@Sendable` closure `PythonRunner` uses to check
/// for cancellation between output lines.
final class CancelFlag: @unchecked Sendable {
    private let lock = NSLock()
    private var value = false

    func set() {
        lock.lock(); defer { lock.unlock() }
        value = true
    }

    func reset() {
        lock.lock(); defer { lock.unlock() }
        value = false
    }

    func isSet() -> Bool {
        lock.lock(); defer { lock.unlock() }
        return value
    }
}

/// Mirrors the WinForms `MainForm`: owns all app state and drives the
/// `python -m nam2zoom` backend the same way `RunPythonAsync` did, including
/// the same guarded-install confirmation text and hash approval flow.
@MainActor
final class AppViewModel: ObservableObject {
    @Published var models: [ModelEntry] = []
    @Published var selectedID: ModelEntry.ID?
    @Published var log: String = ""
    @Published var status: String = "0/5 models  |  Ready"
    @Published var busy = false
    @Published var deviceBusy = false
    @Published var determinateProgress = false
    @Published var progressValue: Double = 0
    @Published var epochs: Int = 100
    @Published var bestEffort = false
    @Published var backupEnabled = true
    @Published var previewRoot: URL?
    @Published var lastAction = "Ready"
    @Published var startupError: String?

    private let cancelFlag = CancelFlag()
    private var jobRunning = false

    let runner: PythonRunner
    let root: URL

    static let bundledDiSha256 =
        "F27F5EA4A1BC4245AF5C4DFF5DE5B75FB7AEF71C1B10E196B35EA5EF41122153"

    init() {
        do {
            let root = try PythonRunner.findRoot()
            self.root = root
            self.runner = PythonRunner(root: root)
        } catch {
            // Fall back to the current directory; every backend call will
            // fail loudly with a clear message instead of crashing here.
            self.root = URL(fileURLWithPath: FileManager.default.currentDirectoryPath)
            self.runner = PythonRunner(root: self.root)
            self.startupError = error.localizedDescription
        }
    }

    // MARK: - App-support paths (macOS analogue of Windows LocalApplicationData)

    private var appSupportDir: URL {
        let base = FileManager.default.urls(for: .applicationSupportDirectory, in: .userDomainMask).first
            ?? FileManager.default.homeDirectoryForCurrentUser
        return base.appendingPathComponent("nam2zoom", isDirectory: true)
    }
    /// Full device backups. The Windows app saves these beside the EXE; a
    /// macOS .app bundle should not be written into, so backups live under
    /// Application Support instead, in a stable, browsable location.
    private var backupDir: URL { appSupportDir.appendingPathComponent("Backup", isDirectory: true) }
    private var sessionsDir: URL { appSupportDir.appendingPathComponent("sessions", isDirectory: true) }
    private var adaptCacheDir: URL { appSupportDir.appendingPathComponent("adapt-cache", isDirectory: true) }

    // MARK: - Selection / validation

    var selectedIndex: Int? { models.firstIndex { $0.id == selectedID } }

    func labelsValid() -> Bool {
        let shapeOk = models.allSatisfy { m in
            (1...5).contains(m.label.count) &&
            m.label.allSatisfy { $0.isASCII && ($0.isLetter || $0.isNumber || $0 == "-" || $0 == "_") }
        }
        guard shapeOk else { return false }
        let upper = models.map { $0.label.uppercased() }
        return Set(upper).count == upper.count
    }

    var canBuild: Bool {
        !busy && !models.isEmpty
            && models.allSatisfy { $0.status == .ready || $0.status == .adapt }
            && labelsValid()
    }
    var canUninstall: Bool { !busy }
    var canCancel: Bool { busy && !deviceBusy && jobRunning && !cancelFlag.isSet() }

    // MARK: - Logging

    private func appendLog(_ line: String) {
        log += line + "\n"
    }

    private func updateActivity(_ line: String) {
        if let match = Self.activityRegex.firstMatch(in: line, range: NSRange(line.startIndex..., in: line)),
           let kindRange = Range(match.range(at: 1), in: line),
           let curRange = Range(match.range(at: 2), in: line),
           let totalRange = Range(match.range(at: 3), in: line),
           let current = Int(line[curRange]), let total = Int(line[totalRange]), total > 0 {
            determinateProgress = true
            progressValue = Double(current) / Double(total)
            status = "Backing up: \(current) of \(total) \(line[kindRange].lowercased())s"
        } else if line.range(of: "Backup complete", options: .caseInsensitive) != nil {
            determinateProgress = false
            status = "Backup complete; checking pedal state"
        } else if line.contains("Starting non-cancellable pedal uninstall") {
            status = "Uninstalling - keep pedal connected"
        } else if line.contains("Starting non-cancellable pedal transfer") {
            status = "Installing - keep pedal connected"
        }
    }
    private static let activityRegex = try! NSRegularExpression(pattern: #"^(Patch|File) (\d+)/(\d+):"#)

    private func streamHandler() -> @Sendable (String) -> Void {
        { [weak self] line in
            DispatchQueue.main.async {
                self?.appendLog(line)
                self?.updateActivity(line)
            }
        }
    }

    private func refreshStatus() {
        status = deviceBusy ? "Pedal operation in progress - do not disconnect"
            : busy ? "Building..." : "\(models.count)/5 models  |  \(lastAction)"
        if !busy {
            determinateProgress = false
            progressValue = 0
        }
    }

    // MARK: - Model list management

    func newLabel(for url: URL) -> String {
        let stemChars = url.deletingPathExtension().lastPathComponent.uppercased()
            .filter { $0.isASCII && ($0.isLetter || $0.isNumber) }
        var stem = String(stemChars.prefix(5))
        if stem.isEmpty { stem = "NAM" }
        func taken(_ candidate: String) -> Bool {
            models.contains { $0.label.caseInsensitiveCompare(candidate) == .orderedSame }
        }
        if !taken(stem) { return stem }
        for suffix in 2...9 {
            let candidate = String(stem.prefix(4)) + "\(suffix)"
            if !taken(candidate) { return candidate }
        }
        return "NAM"
    }

    func addPaths(_ urls: [URL]) async {
        guard !busy else { return }
        let candidates = urls.filter { $0.pathExtension.lowercased() == "nam" }
        if candidates.isEmpty {
            appendLog("Drop .nam files only.")
            return
        }
        var seen = Set<String>()
        var selected: [URL] = []
        for candidate in candidates {
            let key = candidate.path.lowercased()
            if seen.contains(key) { continue }
            seen.insert(key)
            if models.contains(where: { $0.path.path.caseInsensitiveCompare(candidate.path) == .orderedSame }) {
                continue
            }
            selected.append(candidate)
        }
        if selected.isEmpty { return }
        if models.count + selected.count > 5 {
            showAlert(title: "nam2zoom", message: "The current bank supports at most five models.")
            return
        }
        busy = true
        refreshStatus()
        for path in selected {
            if models.contains(where: { $0.path.path.caseInsensitiveCompare(path.path) == .orderedSame }) {
                continue
            }
            var entry = ModelEntry(path: path, label: newLabel(for: path))
            entry.status = .checking
            models.append(entry)
            let index = models.count - 1
            do {
                let result = try await runner.run(["inspect-hybrid", path.path])
                if result.exitCode == 0 {
                    if let data = result.output.data(using: .utf8),
                       let json = try? JSONSerialization.jsonObject(with: data) as? [String: Any] {
                        let statusStr = json["status"] as? String
                        models[index].status = statusStr == "direct" ? .ready
                            : statusStr == "adaptable" ? .adapt : .unsupported
                        if let rate = json["sample_rate"] as? Int {
                            models[index].sampleRate = rate
                        }
                        if models[index].status == .unsupported, let reason = json["reason"] as? String {
                            appendLog("\(path.lastPathComponent): \(reason)")
                        }
                    } else {
                        models[index].status = .unsupported
                    }
                } else {
                    models[index].status = .unsupported
                    appendLog("\(path.lastPathComponent): \(result.output.trimmingCharacters(in: .whitespacesAndNewlines))")
                }
            } catch {
                models[index].status = .unsupported
                appendLog("Validation failed: \(error.localizedDescription)")
            }
        }
        busy = false
        refreshStatus()
    }

    func removeSelected() {
        guard !busy, let idx = selectedIndex else { return }
        models.remove(at: idx)
        selectedID = models.indices.contains(idx) ? models[idx].id
            : models.indices.contains(idx - 1) ? models[idx - 1].id : nil
        refreshStatus()
    }

    func moveSelected(_ direction: Int) {
        guard !busy, let idx = selectedIndex else { return }
        let destination = idx + direction
        guard destination >= 0, destination < models.count else { return }
        models.swapAt(idx, destination)
        selectedID = models[destination].id
    }

    func setLabel(_ raw: String, forSelected id: ModelEntry.ID) {
        guard let idx = models.firstIndex(where: { $0.id == id }) else { return }
        let cleaned = String(raw.uppercased()
            .filter { $0.isASCII && ($0.isLetter || $0.isNumber || $0 == "-" || $0 == "_") }
            .prefix(5))
        models[idx].label = cleaned
    }

    func chooseIr(for id: ModelEntry.ID) {
        guard !busy, models.contains(where: { $0.id == id }) else { return }
        let panel = NSOpenPanel()
        panel.title = "Choose a mono cab IR"
        panel.allowedContentTypes = [UTType(filenameExtension: "wav") ?? .audio]
        panel.allowsMultipleSelection = false
        guard panel.runModal() == .OK, let url = panel.url else { return }
        guard let idx = models.firstIndex(where: { $0.id == id }) else { return }
        models[idx].irPath = url
        previewRoot = nil
    }

    func clearIr(for id: ModelEntry.ID) {
        guard !busy, let idx = models.firstIndex(where: { $0.id == id }) else { return }
        models[idx].irPath = nil
        previewRoot = nil
    }

    // MARK: - Save / open project list

    func saveProject() {
        guard !busy, !models.isEmpty else { return }
        let panel = NSSavePanel()
        panel.title = "Save model list"
        panel.nameFieldStringValue = "models.n2zbank.json"
        guard panel.runModal() == .OK, let url = panel.url else { return }
        let snapshot = models.map {
            ModelEntrySnapshot(Path: $0.path.path, Label: $0.label, IrPath: $0.irPath?.path)
        }
        do {
            let encoder = JSONEncoder()
            encoder.outputFormatting = [.prettyPrinted]
            let data = try encoder.encode(snapshot)
            try data.write(to: url)
            appendLog("Saved \(url.path)")
        } catch {
            showAlert(title: "Save failed", message: error.localizedDescription)
        }
    }

    func openProject() async {
        guard !busy else { return }
        let panel = NSOpenPanel()
        panel.title = "Open model list"
        panel.allowsMultipleSelection = false
        guard panel.runModal() == .OK, let url = panel.url else { return }
        do {
            let data = try Data(contentsOf: url)
            let entries = try JSONDecoder().decode([ModelEntrySnapshot].self, from: data)
            guard !entries.isEmpty else { throw SimpleError("Empty list") }
            if entries.count > 5 || entries.contains(where: { !FileManager.default.fileExists(atPath: $0.Path) }) {
                throw SimpleError("List exceeds five models or contains missing files")
            }
            if entries.contains(where: { entry in
                guard let ir = entry.IrPath else { return false }
                return !FileManager.default.fileExists(atPath: ir) || !ir.lowercased().hasSuffix(".wav")
            }) {
                throw SimpleError("List contains a missing or invalid cab IR WAV")
            }
            let lowerPaths = entries.map { $0.Path.lowercased() }
            if Set(lowerPaths).count != entries.count {
                throw SimpleError("List contains the same NAM file more than once")
            }
            let labelsShapeOk = entries.allSatisfy { entry in
                (1...5).contains(entry.Label.count)
                    && entry.Label.allSatisfy { $0.isASCII && ($0.isLetter || $0.isNumber || $0 == "-" || $0 == "_") }
            }
            let upperLabels = entries.map { $0.Label.uppercased() }
            if !labelsShapeOk || Set(upperLabels).count != entries.count {
                throw SimpleError("List contains invalid or duplicate pedal labels")
            }
            models.removeAll()
            await addPaths(entries.map { URL(fileURLWithPath: $0.Path) })
            for (i, entry) in entries.enumerated() where i < models.count {
                models[i].label = entry.Label
                models[i].irPath = entry.IrPath.map { URL(fileURLWithPath: $0) }
            }
        } catch {
            showAlert(title: "Open failed", message: error.localizedDescription)
        }
    }

    // MARK: - Shared training DI

    /// Reuses the WinForms app's own training DI instead of bundling a second
    /// 16 MB copy into this app - same repo, same file, read directly.
    private func ensureBundledTrainingDi() throws -> URL {
        let shared = root.appendingPathComponent("apps/nam2zoom-desktop/Assets/TRAINING_DI.wav")
        guard let data = try? Data(contentsOf: shared) else {
            throw SimpleError("Shared training DI is missing at \(shared.path)")
        }
        guard Self.sha256Hex(data) == Self.bundledDiSha256 else {
            throw SimpleError("Shared training DI failed its SHA-256 check")
        }
        return shared
    }

    private static func sha256Hex(_ data: Data) -> String {
        SHA256.hash(data: data).map { String(format: "%02X", $0) }.joined()
    }

    // MARK: - Preview

    func openPreview() {
        guard let previewRoot, FileManager.default.fileExists(atPath: previewRoot.path) else { return }
        NSWorkspace.shared.open(previewRoot)
    }

    // MARK: - Confirmation dialogs

    private func showAlert(title: String, message: String, style: NSAlert.Style = .informational) {
        let alert = NSAlert()
        alert.messageText = title
        alert.informativeText = message
        alert.alertStyle = style
        alert.runModal()
    }

    /// Yes/No confirmation defaulting to "No", matching the WinForms dialogs'
    /// `MessageBoxDefaultButton.Button2`.
    private func confirmYesNo(title: String, message: String) -> Bool {
        let alert = NSAlert()
        alert.messageText = title
        alert.informativeText = message
        alert.alertStyle = .warning
        alert.addButton(withTitle: "No")
        alert.addButton(withTitle: "Yes")
        return alert.runModal() == .alertSecondButtonReturn
    }

    // MARK: - Uninstall

    func uninstall() async {
        guard canUninstall else { return }
        let fullBackup = backupEnabled
        let message = "Remove N2Z Bank from the connected supported MS Plus pedal? The app will verify the pedal, "
            + "autosave setting, all saved patches, and the installed effect before writing. "
            + (fullBackup
                ? "A full device backup will be saved under Application Support. "
                : "No full device backup will be saved; only the prior effect list and bank files "
                  + "will be retained in a local session. ")
            + "Keep a stock patch selected, autosave OFF, and the pedal powered and connected. "
            + "Do not disconnect during removal. A failed transfer could leave the pedal unusable.\n\n"
            + "Approve uninstalling N2Z Bank?"
        guard confirmYesNo(title: "Approve pedal uninstall", message: message) else { return }

        busy = true
        deviceBusy = true
        refreshStatus()
        appendLog(fullBackup
            ? "Starting guarded pedal backup and uninstall. Do not disconnect."
            : "Starting guarded uninstall without full backup. Do not disconnect.")
        defer {
            deviceBusy = false
            busy = false
            refreshStatus()
        }
        do {
            let sessionRoot = fullBackup ? backupDir : sessionsDir
            try FileManager.default.createDirectory(at: sessionRoot, withIntermediateDirectories: true)
            var args = ["uninstall-bank", "--session", sessionRoot.appendingPathComponent(timestamp()).path, "--ack-risk"]
            if !fullBackup { args.append("--no-backup") }
            let result = try await runner.run(args, onLine: streamHandler())
            if result.exitCode != 0 {
                throw SimpleError("Pedal operation stopped. Keep the pedal powered; read the log before reconnecting or retrying.")
            }
            let absent = result.output.contains("N2Z Bank is not installed;")
            lastAction = absent ? "N2Z Bank was not installed" : "N2Z Bank uninstalled and verified"
            showAlert(title: "Pedal uninstall complete",
                message: absent ? "N2Z Bank is not installed; no pedal files were changed."
                    : "N2Z Bank was uninstalled and verified.")
        } catch {
            appendLog("Operation stopped: \(error.localizedDescription)")
            lastAction = "Pedal operation stopped - see log"
            showAlert(title: "Pedal operation stopped", message: error.localizedDescription, style: .warning)
        }
    }

    // MARK: - Build / Install

    func cancelBuild() {
        cancelFlag.set()
    }

    func build(installAfterBuild: Bool) async {
        guard labelsValid() else {
            showAlert(title: "nam2zoom", message: "Use unique 1-5 character pedal labels.")
            return
        }
        guard canBuild else { return }

        let fullBackup = backupEnabled
        let bestEffortFlag = bestEffort
        let epochsValue = epochs

        let panel = NSOpenPanel()
        panel.title = "Choose a folder for the build"
        panel.canChooseFiles = false
        panel.canChooseDirectories = true
        panel.allowsMultipleSelection = false
        guard panel.runModal() == .OK, let chosen = panel.url else { return }
        let output = chosen.appendingPathComponent("n2z-bank-\(timestamp())")

        cancelFlag.reset()
        jobRunning = true
        busy = true
        previewRoot = nil
        refreshStatus()
        appendLog("Building \(models.count) model(s) -> \(output.path)")
        if models.contains(where: { $0.status == .adapt || $0.irPath != nil }) {
            appendLog("PC adaptation: \(epochsValue) epochs")
        }

        defer {
            jobRunning = false
            deviceBusy = false
            busy = false
            refreshStatus()
        }

        do {
            let trainingDi = models.contains(where: { $0.status == .adapt || $0.irPath != nil })
                ? try ensureBundledTrainingDi() : nil

            var resolved: [String] = []
            var previews: [(label: String, directory: URL)] = []
            var lowFidelity: [String] = []
            var irLevelChanges: [String] = []

            for model in models {
                if model.status == .ready && model.irPath == nil {
                    resolved.append(model.path.path)
                    continue
                }
                try FileManager.default.createDirectory(at: adaptCacheDir, withIntermediateDirectories: true)
                appendLog("Adapting \(model.fileName)"
                    + (model.irPath.map { " with \($0.lastPathComponent)" } ?? ""))
                var adaptArgs = [
                    "adapt", model.path.path,
                    "--training-di", trainingDi!.path,
                    "--cache", adaptCacheDir.path,
                    "--epochs", String(epochsValue),
                ]
                if bestEffortFlag { adaptArgs.append("--best-effort") }
                if let ir = model.irPath {
                    adaptArgs.append("--ir")
                    adaptArgs.append(ir.path)
                }
                let adaptResult = try await runner.run(
                    adaptArgs, training: true, onLine: streamHandler(),
                    isCancelled: { [weak self] in self?.cancelFlag.isSet() ?? false }
                )
                let lines = adaptResult.output.split(separator: "\n").map { $0.trimmingCharacters(in: .whitespaces) }
                guard adaptResult.exitCode == 0,
                      let marker = lines.last(where: { $0.hasPrefix("READY_MODEL=") }),
                      FileManager.default.fileExists(atPath: String(marker.dropFirst("READY_MODEL=".count)))
                else {
                    throw SimpleError("Adaptation failed for \(model.label); see the build log.")
                }
                resolved.append(String(marker.dropFirst("READY_MODEL=".count)))

                guard let qualityLine = lines.last(where: { $0.hasPrefix("QUALITY_RESULT=") }) else {
                    throw SimpleError("Adaptation produced no quality result for \(model.label)")
                }
                let qualityJSON = String(qualityLine.dropFirst("QUALITY_RESULT=".count))
                if let data = qualityJSON.data(using: .utf8),
                   let quality = try? JSONSerialization.jsonObject(with: data) as? [String: Any] {
                    if quality["status"] as? String == "best-effort" {
                        let esr = (quality["esr"] as? Double) ?? 0
                        let correlation = (quality["correlation"] as? Double) ?? 0
                        lowFidelity.append("\(model.label): ESR \(String(format: "%.4f", esr)), "
                            + "correlation \(String(format: "%.4f", correlation))")
                    }
                    if let irGain = quality["ir_gain_db"] as? Double, irGain < -0.1 {
                        irLevelChanges.append("\(model.label): \(String(format: "%.2f", irGain)) dB")
                    }
                }

                guard let previewLine = lines.last(where: { $0.hasPrefix("PREVIEW_DIR=") }) else {
                    throw SimpleError("Adaptation produced no A/B preview for \(model.label)")
                }
                let previewDir = URL(fileURLWithPath: String(previewLine.dropFirst("PREVIEW_DIR=".count)))
                guard FileManager.default.fileExists(atPath: previewDir.path) else {
                    throw SimpleError("Adaptation produced no A/B preview for \(model.label)")
                }
                previews.append((model.label, previewDir))
            }

            var buildArgs = ["build-bank"]
            buildArgs.append(contentsOf: resolved)
            for model in models {
                buildArgs.append("--label")
                buildArgs.append(model.label)
            }
            buildArgs.append("--output")
            buildArgs.append(output.path)
            let bankResult = try await runner.run(
                buildArgs, onLine: streamHandler(),
                isCancelled: { [weak self] in self?.cancelFlag.isSet() ?? false }
            )
            if bankResult.exitCode != 0 { throw SimpleError("Effect build failed; see the log.") }
            if cancelFlag.isSet() { throw PythonRunner.RunnerError.cancelled }

            let effect = output.appendingPathComponent("build/N2ZBANK.ZD2")
            let icon = output.appendingPathComponent("build/N2ZBANK.ZIC")
            guard FileManager.default.fileExists(atPath: effect.path),
                  FileManager.default.fileExists(atPath: icon.path) else {
                throw SimpleError("Build did not produce the effect and icon pair.")
            }

            if !previews.isEmpty {
                let previewRootURL = output.appendingPathComponent("preview")
                for (label, source) in previews {
                    let destination = previewRootURL.appendingPathComponent(label)
                    try FileManager.default.createDirectory(at: destination, withIntermediateDirectories: true)
                    for name in ["original.wav", "converted.wav"] {
                        try? FileManager.default.copyItem(
                            at: source.appendingPathComponent(name),
                            to: destination.appendingPathComponent(name))
                    }
                }
                previewRoot = previewRootURL
            }

            lastAction = lowFidelity.isEmpty ? "Offline build complete" : "Best-effort build complete"

            if !installAfterBuild {
                var warning = ""
                if !lowFidelity.isEmpty {
                    warning += "\n\nLower-fidelity conversion:\n" + lowFidelity.joined(separator: "\n")
                        + "\nListen using Open A/B before installing."
                }
                if !irLevelChanges.isEmpty {
                    warning += "\n\nCab IR output was attenuated to avoid clipping:\n"
                        + irLevelChanges.joined(separator: "\n")
                        + "\nExpect a lower level; listen to the A/B preview."
                }
                showAlert(title: "Build complete",
                    message: "Offline effect built in:\n\(output.appendingPathComponent("build").path)" + warning)
                return
            }

            if !lowFidelity.isEmpty {
                openPreview()
                let proceed = confirmYesNo(title: "Review conversion",
                    message: "This bank contains a lower-fidelity conversion:\n" + lowFidelity.joined(separator: "\n")
                        + "\n\nThe A/B preview folder has been opened. Listen to the original and "
                        + "converted clips before deciding. Continue to the separate pedal install approval?")
                if !proceed {
                    appendLog("Install declined; best-effort offline build remains available.")
                    return
                }
            }

            let effectData = try Data(contentsOf: effect)
            let iconData = try Data(contentsOf: icon)
            let effectHash = Self.sha256Hex(effectData)
            let iconHash = Self.sha256Hex(iconData)

            var installMessage = fullBackup
                ? "The app will save a full device backup before replacing N2Z Bank. "
                : "No full device backup will be saved. The app will still inspect all saved patches "
                  + "and retain the current effect list and bank files for recovery. "
                  + "If installation fails, there will be no complete pedal backup. "
            installMessage += "An existing N2Z Bank will be uninstalled first. "
                + "It will refuse if the current or any saved patch contains a non-stock effect.\n\n"
                + "Supported targets are MS-50G+ firmware 1.40 and MS-70CDR+ firmware 1.20. "
                + "The bank has been hardware-tested on MS-50G+ only; MS-70CDR+ support is experimental.\n\n"
            if !irLevelChanges.isEmpty {
                installMessage += "Cab IR level reduction to avoid clipping: "
                    + irLevelChanges.joined(separator: ", ") + ". Expect a lower output level.\n\n"
            }
            installMessage += "The 14-layer, 3-channel optimized bank declares 150 load. "
                + "One exact build passed saved-patch boot tests with ZNR, RackComp, TS Drive, Hall REV, and LowPassFL. "
                + "A saved patch with FD B-MAN showed PROCESS OVERFLOW on N2Z after reboot. "
                + "This newly built binary has not passed a saved-patch test. "
                + "Do not save it in a patch until separately tested. "
            if !lowFidelity.isEmpty { installMessage += "It contains a lower-fidelity NAM conversion. " }
            installMessage += "Its memory use and real-time load are unverified. "
                + "It could slow, crackle, freeze, or permanently disable the device. "
                + "Keep the pedal powered and connected. "
                + "Use it as the sole effect for initial audition.\n\n"
                + "N2ZBANK.ZD2 SHA-256: \(effectHash)\nN2ZBANK.ZIC SHA-256: \(iconHash)\n\n"
                + "Do you approve installing this exact pair?"

            guard confirmYesNo(title: "Approve pedal install", message: installMessage) else {
                appendLog("Install declined; offline build remains available.")
                return
            }

            deviceBusy = true
            refreshStatus()
            appendLog(fullBackup
                ? "Starting guarded pedal backup and install. Do not disconnect."
                : "Starting guarded install without full backup. Do not disconnect.")
            let sessionRoot = fullBackup ? backupDir : sessionsDir
            try FileManager.default.createDirectory(at: sessionRoot, withIntermediateDirectories: true)
            var installArgs = [
                "install-bank", effect.path,
                "--session", sessionRoot.appendingPathComponent(timestamp()).path,
                "--approved-zd2-sha256", effectHash,
                "--approved-zic-sha256", iconHash,
                "--ack-risk",
            ]
            if !fullBackup { installArgs.append("--no-backup") }
            let installResult = try await runner.run(installArgs, onLine: streamHandler())
            if installResult.exitCode != 0 {
                throw SimpleError("Pedal operation stopped. Keep the pedal powered; read the log before reconnecting or retrying.")
            }
            lastAction = "N2Z Bank installed and verified"
            showAlert(title: "Install complete",
                message: "N2Z Bank is installed and verified. "
                    + "Test this build first in an unsaved patch; its saved-patch boot behavior is unverified.")
        } catch PythonRunner.RunnerError.cancelled {
            appendLog("Build cancelled. No pedal files were changed.")
            lastAction = "Build cancelled"
        } catch {
            appendLog("Operation stopped: \(error.localizedDescription)")
            lastAction = deviceBusy ? "Pedal operation stopped - see log" : "Build failed"
            showAlert(title: deviceBusy ? "Pedal operation stopped" : "Build failed",
                message: error.localizedDescription, style: .warning)
        }
    }

    private func timestamp() -> String {
        let formatter = DateFormatter()
        formatter.dateFormat = "yyyyMMdd-HHmmss-SSS"
        return formatter.string(from: Date())
    }
}
