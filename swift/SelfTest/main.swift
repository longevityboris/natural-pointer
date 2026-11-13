// Checks that HumanStroke.swift gives the paths the Python package gives for the same seeds.
//
//     swiftc -O swift/HumanStroke.swift swift/SelfTest/main.swift -o swift/.build/selftest
//     swift/.build/selftest natural_pointer/data/strokes.json swift/SelfTest/fixtures.json

import Foundation

struct Fixtures: Decodable {
    struct Call: Decodable {
        let start: [Double]?
        let end: [Double]?
        let screen: [Double]?
        let stroke: Int?
        let t: [Double]?
        let x: [Double]?
        let y: [Double]?
        let dwell: Double?        // a dwell() call instead of a path() call
        let at: [[Double]]?       // [when, x, y] from position_at
    }
    struct Case: Decodable { let seed: UInt64; let calls: [Call] }
    let tolerance: Double
    let cases: [Case]
}

func fail(_ message: String) -> Never {
    FileHandle.standardError.write(Data(("FAIL: " + message + "\n").utf8))
    exit(1)
}

let args = CommandLine.arguments
guard args.count == 3 else { fail("usage: selftest <strokes.json> <fixtures.json>") }
let libraryData = try Data(contentsOf: URL(fileURLWithPath: args[1]))
let fixtures = try JSONDecoder().decode(Fixtures.self, from: Data(contentsOf: URL(fileURLWithPath: args[2])))

var paths = 0, points = 0, worst = 0.0
func close(_ got: Double, _ want: Double, _ what: String) {
    let off = abs(got - want)
    worst = max(worst, off)
    if !(off <= fixtures.tolerance) { fail("\(what): got \(got), Python gave \(want)") }
}

for test in fixtures.cases {
    var hand = try HumanStrokeLibrary(data: libraryData, seed: test.seed)
    for (n, call) in test.calls.enumerated() {
        let label = "seed \(test.seed) call \(n)"
        if let want = call.dwell {
            close(hand.dwell(), want, "\(label) dwell")
            continue
        }
        guard let s = call.start, let e = call.end, let t = call.t, let x = call.x, let y = call.y else {
            fail("\(label): malformed fixture")
        }
        let path = hand.path(from: (s[0], s[1]), to: (e[0], e[1]), screen: call.screen.map { ($0[0], $0[1]) })
        if path.strokeId != (call.stroke ?? -1) { fail("\(label): stroke \(path.strokeId), Python chose \(call.stroke ?? -1)") }
        if path.t.count != t.count { fail("\(label): \(path.t.count) points, Python gave \(t.count)") }
        for i in 0..<t.count {
            close(path.t[i], t[i], "\(label) t[\(i)]")
            close(path.x[i], x[i], "\(label) x[\(i)]")
            close(path.y[i], y[i], "\(label) y[\(i)]")
        }
        for probe in call.at ?? [] {
            let p = path.position(at: probe[0])
            close(p.x, probe[1], "\(label) position(at: \(probe[0])).x")
            close(p.y, probe[2], "\(label) position(at: \(probe[0])).y")
        }
        if path.x[0] != s[0] || path.y[0] != s[1] || path.t[0] != 0 { fail("\(label): does not start at the start") }
        if path.x[t.count - 1] != e[0] || path.y[t.count - 1] != e[1] { fail("\(label): does not end at the end") }
        paths += 1
        points += t.count
    }
}
print("ok: \(paths) paths, \(points) points match Python (largest difference \(worst))")
