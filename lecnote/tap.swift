// lecnote-tap — record one application's audio through a Core Audio process
// tap (macOS 14.2+). The app keeps playing to whatever output it uses; the tap
// only listens. No virtual device, no rerouting, volume keys keep working.
//
//   lecnote-tap list                         audio clients the system knows about
//   lecnote-tap record --app firefox --out audio.wav
//
// Writes 16 kHz mono 16-bit WAV — what the rest of lecnote expects — and, on
// SIGTERM or SIGINT, closes the file and writes <out>.stats.json with the
// duration and peak level, the same contract as the microphone recorder.

import AVFoundation
import CoreAudio
import Darwin
import Foundation

func note(_ msg: String) {
    FileHandle.standardError.write((msg + "\n").data(using: .utf8)!)
}

func fail(_ msg: String, _ status: OSStatus = noErr) -> Never {
    note("error: \(msg)" + (status == noErr ? "" : " (OSStatus \(status))"))
    exit(1)
}

func address(_ sel: AudioObjectPropertySelector) -> AudioObjectPropertyAddress {
    AudioObjectPropertyAddress(mSelector: sel,
                               mScope: kAudioObjectPropertyScopeGlobal,
                               mElement: kAudioObjectPropertyElementMain)
}

func readValue<T>(_ obj: AudioObjectID, _ sel: AudioObjectPropertySelector, _ initial: T) -> T? {
    var addr = address(sel)
    var size = UInt32(MemoryLayout<T>.size)
    var value = initial
    return AudioObjectGetPropertyData(obj, &addr, 0, nil, &size, &value) == noErr ? value : nil
}

func readIDs(_ obj: AudioObjectID, _ sel: AudioObjectPropertySelector) -> [AudioObjectID] {
    var addr = address(sel)
    var size: UInt32 = 0
    guard AudioObjectGetPropertyDataSize(obj, &addr, 0, nil, &size) == noErr, size > 0 else { return [] }
    var ids = [AudioObjectID](repeating: 0, count: Int(size) / MemoryLayout<AudioObjectID>.size)
    guard AudioObjectGetPropertyData(obj, &addr, 0, nil, &size, &ids) == noErr else { return [] }
    return ids
}

func readString(_ obj: AudioObjectID, _ sel: AudioObjectPropertySelector) -> String? {
    var addr = address(sel)
    var value: Unmanaged<CFString>?
    var size = UInt32(MemoryLayout<Unmanaged<CFString>?>.size)
    let status = withUnsafeMutablePointer(to: &value) {
        AudioObjectGetPropertyData(obj, &addr, 0, nil, &size, $0)
    }
    guard status == noErr, let v = value else { return nil }
    return v.takeRetainedValue() as String
}

func executablePath(_ pid: pid_t) -> String {
    var buf = [CChar](repeating: 0, count: 4096)
    return proc_pidpath(pid, &buf, UInt32(buf.count)) > 0 ? String(cString: buf) : ""
}

struct AudioProcess {
    let object: AudioObjectID
    let pid: pid_t
    let bundle: String
    let path: String
    let playing: Bool
}

func audioProcesses() -> [AudioProcess] {
    readIDs(AudioObjectID(kAudioObjectSystemObject), kAudioHardwarePropertyProcessObjectList).map {
        let pid = readValue($0, kAudioProcessPropertyPID, pid_t(-1)) ?? -1
        return AudioProcess(object: $0, pid: pid,
                            bundle: readString($0, kAudioProcessPropertyBundleID) ?? "",
                            path: executablePath(pid),
                            playing: (readValue($0, kAudioProcessPropertyIsRunningOutput, UInt32(0)) ?? 0) != 0)
    }
}

// Browsers play audio from helper processes, not the main one — Firefox from
// plugin-container, Chrome from "Google Chrome Helper" — so match on where the
// executable lives as well as the bundle id. Every helper sits inside the app.
func matching(_ app: String) -> [AudioProcess] {
    let want = app.lowercased()
    return audioProcesses().filter {
        $0.pid != getpid() && ($0.bundle.lowercased().contains(want) || $0.path.lowercased().contains(want))
    }
}

// --- list -------------------------------------------------------------------

func list() -> Never {
    let procs = audioProcesses().sorted { $0.path < $1.path }
    if procs.isEmpty { note("no audio clients registered right now") }
    for p in procs {
        let name = p.path.isEmpty ? "?" : URL(fileURLWithPath: p.path).lastPathComponent
        print("\(p.playing ? "♪" : " ") \(String(p.pid).padding(toLength: 6, withPad: " ", startingAt: 0)) "
              + "\(name.padding(toLength: 34, withPad: " ", startingAt: 0)) \(p.bundle)")
    }
    exit(0)
}

// --- record -----------------------------------------------------------------

final class Session {
    let app: String
    let out: URL
    let description: CATapDescription
    var tap = AudioObjectID(kAudioObjectUnknown)
    var aggregate = AudioObjectID(kAudioObjectUnknown)
    var ioProc: AudioDeviceIOProcID?
    var file: AVAudioFile?
    var converter: AVAudioConverter!
    var inFormat: AVAudioFormat!
    let outFormat = AVAudioFormat(commonFormat: .pcmFormatFloat32, sampleRate: 16000,
                                  channels: 1, interleaved: false)!
    let writer = DispatchQueue(label: "lecnote.tap.writer")
    var frames = 0
    var peak: Float = 0
    var tapped: Set<AudioObjectID> = []
    var timer: DispatchSourceTimer?

    init(app: String, out: URL) {
        self.app = app
        self.out = out
        description = CATapDescription(stereoMixdownOfProcesses: [])
        description.uuid = UUID()
        description.name = "lecnote \(app)"
        description.isPrivate = true
        description.muteBehavior = .unmuted  // the listener still hears it
    }

    func start() {
        let first = matching(app)
        tapped = Set(first.map(\.object))
        description.processes = Array(tapped)

        var status = AudioHardwareCreateProcessTap(description, &tap)
        guard status == noErr else { fail("could not create a tap for '\(app)'", status) }

        var fmt = AudioStreamBasicDescription()
        var addr = address(kAudioTapPropertyFormat)
        var size = UInt32(MemoryLayout<AudioStreamBasicDescription>.size)
        status = AudioObjectGetPropertyData(tap, &addr, 0, nil, &size, &fmt)
        guard status == noErr, let input = AVAudioFormat(streamDescription: &fmt) else {
            fail("could not read the tap's audio format", status)
        }
        inFormat = input
        converter = AVAudioConverter(from: input, to: outFormat)
        converter.downmix = true

        do {
            file = try AVAudioFile(forWriting: out, settings: [
                AVFormatIDKey: kAudioFormatLinearPCM, AVSampleRateKey: 16000,
                AVNumberOfChannelsKey: 1, AVLinearPCMBitDepthKey: 16,
                AVLinearPCMIsFloatKey: false, AVLinearPCMIsBigEndianKey: false,
            ], commonFormat: .pcmFormatFloat32, interleaved: false)
        } catch {
            fail("could not open \(out.path) for writing: \(error.localizedDescription)")
        }

        // A tap is delivered through a private aggregate device. The system
        // output is its clock; the tap is its only input.
        let outputID = readValue(AudioObjectID(kAudioObjectSystemObject),
                                 kAudioHardwarePropertyDefaultSystemOutputDevice,
                                 AudioObjectID(kAudioObjectUnknown)) ?? AudioObjectID(kAudioObjectUnknown)
        guard let outputUID = readString(outputID, kAudioDevicePropertyDeviceUID) else {
            fail("could not find the system output device")
        }
        let aggregateDescription: [String: Any] = [
            kAudioAggregateDeviceNameKey: "lecnote tap",
            kAudioAggregateDeviceUIDKey: UUID().uuidString,
            kAudioAggregateDeviceMainSubDeviceKey: outputUID,
            kAudioAggregateDeviceIsPrivateKey: true,
            kAudioAggregateDeviceIsStackedKey: false,
            kAudioAggregateDeviceTapAutoStartKey: true,
            kAudioAggregateDeviceSubDeviceListKey: [[kAudioSubDeviceUIDKey: outputUID]],
            kAudioAggregateDeviceTapListKey: [[
                kAudioSubTapDriftCompensationKey: true,
                kAudioSubTapUIDKey: description.uuid.uuidString,
            ]],
        ]
        status = AudioHardwareCreateAggregateDevice(aggregateDescription as CFDictionary, &aggregate)
        guard status == noErr else { fail("could not create the capture device", status) }

        status = AudioDeviceCreateIOProcIDWithBlock(&ioProc, aggregate, nil) {
            [unowned self] _, input, _, _, _ in self.receive(input)
        }
        guard status == noErr else { fail("could not attach to the capture device", status) }
        status = AudioDeviceStart(aggregate, ioProc)
        guard status == noErr else { fail("could not start capturing", status) }

        report(first, initial: true)

        // Helper processes come and go — a browser only starts its audio
        // process once something plays — so keep the tapped set current.
        let t = DispatchSource.makeTimerSource(queue: .main)
        t.schedule(deadline: .now() + 0.5, repeating: 0.5)
        t.setEventHandler { [unowned self] in self.rescan() }
        t.resume()
        timer = t
    }

    func report(_ procs: [AudioProcess], initial: Bool) {
        if procs.isEmpty {
            if initial { note("tapping '\(app)': nothing is playing yet — waiting for it") }
            return
        }
        let names = Set(procs.map { $0.path.isEmpty ? $0.bundle : URL(fileURLWithPath: $0.path).lastPathComponent })
        note("tapping '\(app)': \(procs.count) process(es) — \(names.sorted().joined(separator: ", "))")
    }

    func rescan() {
        let now = matching(app)
        let ids = Set(now.map(\.object))
        guard ids != tapped else { return }
        tapped = ids
        description.processes = Array(ids)
        var addr = address(kAudioTapPropertyDescription)
        var desc: CATapDescription = description
        let status = AudioObjectSetPropertyData(tap, &addr, 0, nil,
                                                UInt32(MemoryLayout<CATapDescription>.stride), &desc)
        if status != noErr { note("warning: could not update the tapped processes (OSStatus \(status))") }
        report(now, initial: false)
    }

    // Runs on Core Audio's real-time thread: copy and hand off, nothing more.
    func receive(_ input: UnsafePointer<AudioBufferList>) {
        guard let source = AVAudioPCMBuffer(pcmFormat: inFormat, bufferListNoCopy: input, deallocator: nil),
              source.frameLength > 0,
              let copy = AVAudioPCMBuffer(pcmFormat: inFormat, frameCapacity: source.frameLength)
        else { return }
        copy.frameLength = source.frameLength
        let from = UnsafeMutableAudioBufferListPointer(UnsafeMutablePointer(mutating: input))
        let to = UnsafeMutableAudioBufferListPointer(copy.mutableAudioBufferList)
        for i in 0..<min(from.count, to.count) {
            let bytes = min(from[i].mDataByteSize, to[i].mDataByteSize)
            if let dst = to[i].mData, let src = from[i].mData { memcpy(dst, src, Int(bytes)) }
            to[i].mDataByteSize = bytes
        }
        writer.async { [unowned self] in self.write(copy) }
    }

    func write(_ buffer: AVAudioPCMBuffer) {
        let capacity = AVAudioFrameCount(Double(buffer.frameLength) * 16000 / inFormat.sampleRate) + 64
        guard let out = AVAudioPCMBuffer(pcmFormat: outFormat, frameCapacity: capacity) else { return }
        var given = false
        var error: NSError?
        // .noDataNow rather than .endOfStream keeps the resampler's state
        // between callbacks, so there is no click at every buffer boundary.
        converter.convert(to: out, error: &error) { _, status in
            if given { status.pointee = .noDataNow; return nil }
            given = true
            status.pointee = .haveData
            return buffer
        }
        guard error == nil, out.frameLength > 0, let file = file else { return }
        try? file.write(from: out)
        let samples = out.floatChannelData![0]
        for i in 0..<Int(out.frameLength) { peak = max(peak, abs(samples[i])) }
        frames += Int(out.frameLength)
    }

    func stop() -> Never {
        timer?.cancel()
        if let proc = ioProc {
            AudioDeviceStop(aggregate, proc)
            AudioDeviceDestroyIOProcID(aggregate, proc)
        }
        if aggregate != kAudioObjectUnknown { AudioHardwareDestroyAggregateDevice(aggregate) }
        if tap != kAudioObjectUnknown { AudioHardwareDestroyProcessTap(tap) }
        writer.sync {}  // flush everything already handed off
        file = nil      // closing finalises the WAV header

        let seconds = Double(frames) / 16000
        let stats = out.deletingPathExtension().appendingPathExtension("stats.json")
        let json = String(format: "{\"seconds\": %.3f, \"peak\": %.6f}", seconds, Double(peak))
        try? json.write(to: stats, atomically: true, encoding: .utf8)
        note(String(format: "stopped: %.1fs captured, peak %.3f", seconds, Double(peak)))
        exit(0)
    }
}

// --- main -------------------------------------------------------------------

let args = Array(CommandLine.arguments.dropFirst())
func option(_ name: String) -> String? {
    guard let i = args.firstIndex(of: name), i + 1 < args.count else { return nil }
    return args[i + 1]
}

switch args.first {
case "list":
    list()
case "record":
    guard let app = option("--app"), let out = option("--out") else {
        fail("usage: lecnote-tap record --app NAME --out FILE.wav")
    }
    let session = Session(app: app, out: URL(fileURLWithPath: out))
    session.start()
    var signalSources: [DispatchSourceSignal] = []
    for sig in [SIGTERM, SIGINT] {
        signal(sig, SIG_IGN)
        let source = DispatchSource.makeSignalSource(signal: sig, queue: .main)
        source.setEventHandler { session.stop() }
        source.resume()
        signalSources.append(source)
    }
    dispatchMain()
default:
    fail("usage: lecnote-tap list | record --app NAME --out FILE.wav")
}
