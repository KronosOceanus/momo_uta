import AVFoundation
import Foundation

final class MomoAudio {
    private let engine = AVAudioEngine()
    private let player = AVAudioPlayerNode()
    private var file: AVAudioFile?
    private var duration: Double = 0
    private var position: Double = 0
    private var playing = false
    private var ended = false
    private var anchor: Date?
    private var volume: Double = 1
    private var scheduleToken = 0
    private var activity: NSObjectProtocol?

    init() {
        engine.attach(player)
        engine.mainMixerNode.outputVolume = Float(volume)
    }

    private func keepAwake(_ on: Bool) {
        if on, activity == nil {
            activity = ProcessInfo.processInfo.beginActivity(
                options: .userInitiatedAllowingIdleSystemSleep,
                reason: "Momo audio playback")
        } else if !on, let a = activity {
            ProcessInfo.processInfo.endActivity(a)
            activity = nil
        }
    }

    func load(path: String) -> [String: Any] {
        player.stop()
        playing = false
        ended = false
        anchor = nil
        position = 0
        keepAwake(false)
        let u = URL(fileURLWithPath: path)
        do {
            let f = try AVAudioFile(forReading: u)
            file = f
            duration = Double(f.length) / f.processingFormat.sampleRate
            if !engine.isRunning {
                engine.connect(player, to: engine.mainMixerNode, format: f.processingFormat)
                engine.prepare()
                try engine.start()
            }
            schedule(0)
            return status(ok: true)
        } catch {
            file = nil
            duration = 0
            return ["ok": false, "error": String(describing: error)]
        }
    }

    private func schedule(_ at: Double) {
        guard let f = file else { return }
        scheduleToken += 1
        let token = scheduleToken
        player.stop()
        let rate = f.processingFormat.sampleRate
        let start = AVAudioFramePosition(max(0, min(duration, at)) * rate)
        let remaining = f.length - start
        guard remaining > 0 else {
            position = duration
            ended = true
            return
        }
        position = at
        ended = false
        player.scheduleSegment(f, startingFrame: start,
                               frameCount: AVAudioFrameCount(remaining),
                               at: nil) { [weak self] in
            guard let self, token == self.scheduleToken else { return }
            self.ended = true
            self.playing = false
            self.anchor = nil
            self.position = self.duration
        }
    }

    private func ensureEngine() throws {
        if !engine.isRunning {
            engine.prepare()
            try engine.start()
        }
    }

    func play() -> [String: Any] {
        guard let f = file else { return ["ok": false, "error": "not loaded"] }
        do {
            try ensureEngine()
            if ended || position >= duration {
                schedule(0)
            }
            if !playing {
                if anchor == nil { anchor = Date() }
                player.play()
                playing = true
                ended = false
                keepAwake(true)
            }
            return status(ok: true)
        } catch {
            return ["ok": false, "error": String(describing: error)]
        }
    }

    func pause() -> [String: Any] {
        position = current()
        anchor = nil
        player.pause()
        playing = false
        keepAwake(false)
        return status(ok: true)
    }

    func seek(_ seconds: Double) -> [String: Any] {
        guard file != nil else { return ["ok": false, "error": "not loaded"] }
        let wasPlaying = playing
        let t = max(0, min(duration, seconds))
        schedule(t)
        if wasPlaying {
            do {
                try ensureEngine()
                player.play()
                playing = true
                anchor = Date()
                keepAwake(true)
            } catch {
                return ["ok": false, "error": String(describing: error)]
            }
        } else {
            position = t
        }
        return status(ok: true)
    }

    func setVolume(_ v: Double) -> [String: Any] {
        volume = max(0, min(1, v))
        engine.mainMixerNode.outputVolume = Float(volume)
        return status(ok: true)
    }

    func current() -> Double {
        if playing, let anchor {
            return min(duration, position + Date().timeIntervalSince(anchor))
        }
        return position
    }

    func status(ok: Bool = true) -> [String: Any] {
        var d: [String: Any] = [
            "ok": ok,
            "state": playing ? "playing" : (ended ? "ended" : "paused"),
            "current": current(),
            "duration": duration,
            "volume": volume,
            "ended": ended,
        ]
        if let f = file {
            d["path"] = f.url.path
        }
        return d
    }

    func stop() -> [String: Any] {
        player.stop()
        playing = false
        anchor = nil
        position = 0
        ended = false
        keepAwake(false)
        return status(ok: true)
    }
}

func emit(_ obj: [String: Any]) {
    guard let data = try? JSONSerialization.data(withJSONObject: obj),
          let text = String(data: data, encoding: .utf8) else { return }
    print(text)
    fflush(stdout)
}

let audio = MomoAudio()

if CommandLine.arguments.count >= 3 && CommandLine.arguments[1] == "play" {
    let load = audio.load(path: CommandLine.arguments[2])
    emit(load)
    if load["ok"] as? Bool == true {
        emit(audio.play())
        while true {
            Thread.sleep(forTimeInterval: 0.25)
            let st = audio.status()
            if st["ended"] as? Bool == true {
                emit(st)
                break
            }
        }
    }
    exit(0)
}

while let line = readLine() {
    guard let data = line.data(using: .utf8),
          let obj = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
          let cmd = obj["cmd"] as? String else {
        emit(["ok": false, "error": "bad json"])
        continue
    }
    switch cmd {
    case "load":
        guard let path = obj["path"] as? String else {
            emit(["ok": false, "error": "missing path"]); continue
        }
        emit(audio.load(path: path))
    case "play":
        emit(audio.play())
    case "pause":
        emit(audio.pause())
    case "seek":
        emit(audio.seek((obj["seconds"] as? NSNumber)?.doubleValue ?? 0))
    case "volume":
        emit(audio.setVolume((obj["value"] as? NSNumber)?.doubleValue ?? 1))
    case "status":
        emit(audio.status())
    case "stop":
        emit(audio.stop())
    case "quit":
        emit(audio.stop())
        exit(0)
    default:
        emit(["ok": false, "error": "unknown command"])
    }
}
