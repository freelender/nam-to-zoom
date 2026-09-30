import Foundation

/// Runs the `python -m nam2zoom` backend as a subprocess, the same way the
/// original WinForms app's `RunPythonAsync` does, streaming stdout/stderr
/// line-by-line to a callback.
final class PythonRunner: @unchecked Sendable {
    let root: URL

    struct RunResult {
        let exitCode: Int32
        let output: String
    }

    enum RunnerError: LocalizedError {
        case rootNotFound
        case pythonMissing(URL)
        case launchFailed(String)
        case cancelled

        var errorDescription: String? {
            switch self {
            case .rootNotFound:
                return "Could not find tools/nam2zoom next to this app. " +
                    "Run this app from inside the project checkout."
            case .pythonMissing(let url):
                return "Backend Python is missing at \(url.path). Run setup-mac.sh first."
            case .launchFailed(let message):
                return "Could not start Python: \(message)"
            case .cancelled:
                return "Operation cancelled"
            }
        }
    }

    init(root: URL) {
        self.root = root
    }

    /// Every in-flight backend subprocess, so the app can terminate them on
    /// quit instead of leaving orphaned python/core_render processes behind.
    private static let activeProcessesLock = NSLock()
    private static var activeProcesses: [ObjectIdentifier: Process] = [:]

    private static func register(_ process: Process) {
        activeProcessesLock.lock()
        activeProcesses[ObjectIdentifier(process)] = process
        activeProcessesLock.unlock()
    }

    private static func unregister(_ process: Process) {
        activeProcessesLock.lock()
        activeProcesses.removeValue(forKey: ObjectIdentifier(process))
        activeProcessesLock.unlock()
    }

    /// Terminates every backend subprocess this runner has started that is
    /// still running. Called when the app is quitting.
    static func terminateAllActive() {
        activeProcessesLock.lock()
        let processes = Array(activeProcesses.values)
        activeProcessesLock.unlock()
        for process in processes where process.isRunning {
            process.terminate()
        }
    }

    static func findRoot() throws -> URL {
        var directory = URL(fileURLWithPath: CommandLine.arguments[0])
            .resolvingSymlinksInPath()
            .deletingLastPathComponent()
        let fm = FileManager.default
        while true {
            let marker = directory
                .appendingPathComponent("tools")
                .appendingPathComponent("nam2zoom")
                .appendingPathComponent("__main__.py")
            if fm.fileExists(atPath: marker.path) {
                return directory
            }
            let parent = directory.deletingLastPathComponent()
            if parent.path == directory.path {
                throw RunnerError.rootNotFound
            }
            directory = parent
        }
    }

    var stomphacksPython: URL {
        root.appendingPathComponent(".tooling/stomphacks/.venv/bin/python3")
    }

    var trainingPython: URL {
        root.appendingPathComponent(".tooling/nam-train-venv/bin/python3")
    }

    /// Runs `python -m nam2zoom <command>`. `onLine` is awaited for each
    /// stdout/stderr line as it arrives (used for live log + progress
    /// parsing); `isCancelled` is polled between lines to support the
    /// Cancel button.
    func run(
        _ command: [String],
        training: Bool = false,
        onLine: (@Sendable (String) -> Void)? = nil,
        isCancelled: (@Sendable () -> Bool)? = nil
    ) async throws -> RunResult {
        let executable = training ? trainingPython : stomphacksPython
        guard FileManager.default.isExecutableFile(atPath: executable.path) else {
            throw RunnerError.pythonMissing(executable)
        }

        let process = Process()
        process.executableURL = executable
        process.arguments = ["-u", "-m", "nam2zoom"] + command
        process.currentDirectoryURL = root
        var env = ProcessInfo.processInfo.environment
        env["PYTHONPATH"] = root.appendingPathComponent("tools").path
        env["PYTHONUNBUFFERED"] = "1"
        process.environment = env

        let stdoutPipe = Pipe()
        let stderrPipe = Pipe()
        process.standardOutput = stdoutPipe
        process.standardError = stderrPipe

        do {
            try process.run()
        } catch {
            throw RunnerError.launchFailed(error.localizedDescription)
        }
        Self.register(process)
        defer { Self.unregister(process) }

        let collected = Collector()

        async let stdoutTask: Void = drain(stdoutPipe, into: collected, onLine: onLine)
        async let stderrTask: Void = drain(stderrPipe, into: collected, onLine: onLine)

        if let isCancelled {
            while process.isRunning {
                if isCancelled() {
                    process.terminate()
                    break
                }
                try? await Task.sleep(nanoseconds: 150_000_000)
            }
        }

        _ = await (stdoutTask, stderrTask)
        process.waitUntilExit()

        if let isCancelled, isCancelled() {
            throw RunnerError.cancelled
        }

        return RunResult(exitCode: process.terminationStatus, output: await collected.text)
    }

    private func drain(
        _ pipe: Pipe,
        into collector: Collector,
        onLine: (@Sendable (String) -> Void)?
    ) async {
        do {
            for try await line in pipe.fileHandleForReading.bytes.lines {
                await collector.append(line)
                onLine?(line)
            }
        } catch {
            // Reading stopped (e.g. the process closed its end abruptly);
            // whatever was captured so far is still returned.
        }
    }

    private actor Collector {
        private(set) var text = ""
        func append(_ line: String) {
            text += line + "\n"
        }
    }
}
