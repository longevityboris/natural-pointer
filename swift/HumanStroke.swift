// HumanStroke.swift
//
// Move the pointer the way a recorded hand moved it. Loads the stroke library
// (natural_pointer/data/strokes.json) and, for a start and an end, returns a
// timed path: a recorded stroke of similar length and direction, turned and
// scaled onto start -> end with its timing, tremor, overshoot and corrections
// as recorded.
//
// Foundation only. A port of StrokeLibrary in natural_pointer/strokes.py: the
// same library file and the same seed give the same path in both
// (swift/SelfTest checks it).
//
//     var hand = try HumanStrokeLibrary(contentsOf: url)
//     let path = hand.path(from: (x0, y0), to: (x1, y1), screen: (width, height))
//     // every tick, steer towards path.position(at: secondsSinceStart)
//     // until secondsSinceStart >= path.duration

import Foundation

/// One recorded stroke in its own frame: start at (0, 0), end at (dist, 0).
public struct HumanStroke {
    public let id: Int
    public let dist: Double      // points from start to end on the recording screen
    public let angle: Double     // direction of start -> end, radians, y down
    public let t: [Double]       // seconds from the start
    public let a: [Double]       // points along start -> end
    public let b: [Double]       // points across it
    public let dwell: Double?    // seconds it then rested before a click, if a click ended it
}

/// A timed path in screen points.
public struct HumanPath {
    public let t: [Double]       // seconds from the start of the move; t[0] is 0
    public let x: [Double]
    public let y: [Double]
    public let strokeId: Int     // the recorded stroke it came from; -1 if none

    public var duration: Double { t.last ?? 0 }

    /// Where the pointer is `when` seconds into the move, straight between the two nearest samples.
    public func position(at when: Double) -> (x: Double, y: Double) {
        guard let first = t.first, let last = t.last else { return (0, 0) }
        if when <= first { return (x[0], y[0]) }
        if when >= last { return (x[x.count - 1], y[y.count - 1]) }
        var lo = 0, hi = t.count - 1
        while hi - lo > 1 {
            let mid = (lo + hi) / 2
            if t[mid] <= when { lo = mid } else { hi = mid }
        }
        let f = t[hi] > t[lo] ? (when - t[lo]) / (t[hi] - t[lo]) : 1.0
        return (x[lo] + (x[hi] - x[lo]) * f, y[lo] + (y[hi] - y[lo]) * f)
    }
}

/// A small seeded generator, the same in Python and Swift.
public struct SplitMix64 {
    public var state: UInt64
    public init(seed: UInt64) { state = seed }

    public mutating func next() -> UInt64 {
        state = state &+ 0x9E3779B97F4A7C15
        var z = state
        z = (z ^ (z >> 30)) &* 0xBF58476D1CE4E5B9
        z = (z ^ (z >> 27)) &* 0x94D049BB133111EB
        return z ^ (z >> 31)
    }

    /// A number in [0, 1).
    public mutating func unit() -> Double { Double(next() >> 11) / 9007199254740992.0 }

    public mutating func between(_ lo: Double, _ hi: Double) -> Double { lo + (hi - lo) * unit() }
}

/// Recorded strokes, and the retargeting of one onto a new start -> end.
public struct HumanStrokeLibrary {
    public static let choices = 6          // pick among this many best-matching strokes
    public static let recentCount = 4      // ...none of which was among the last this many used
    public static let angleWeight = 0.5    // a 90 degree turn costs as much as this many e-folds of length

    public let strokes: [HumanStroke]
    public let fitA: Double                // expected seconds for a move of d points: fitA + fitB * log2(1 + d)
    public let fitB: Double
    public private(set) var recent: [Int] = []
    var rng: SplitMix64

    private struct File: Decodable {
        struct Fit: Decodable { let a: Double; let b: Double }
        struct Stroke: Decodable { let id: Int; let angle: Int; let dwell: Int?; let t: [Int]; let a: [Int]; let b: [Int] }
        let fit: Fit
        let strokes: [Stroke]
    }

    /// `seed` fixes the choices, for tests; leave it out for a fresh one each launch.
    public init(data: Data, seed: UInt64? = nil) throws {
        let file = try JSONDecoder().decode(File.self, from: data)
        strokes = file.strokes.compactMap { s -> HumanStroke? in
            guard s.t.count >= 2, s.t.count == s.a.count, s.t.count == s.b.count,
                  let last = s.a.last, last > 0, let end = s.t.last, end > 0 else { return nil }
            return HumanStroke(id: s.id, dist: Double(last) / 10, angle: Double(s.angle) / 1e4,
                               t: s.t.map { Double($0) / 1e4 }, a: s.a.map { Double($0) / 10 },
                               b: s.b.map { Double($0) / 10 }, dwell: s.dwell.map { Double($0) / 1e4 })
        }
        fitA = file.fit.a
        fitB = file.fit.b
        rng = SplitMix64(seed: seed ?? UInt64.random(in: UInt64.min...UInt64.max))
    }

    public init(contentsOf url: URL, seed: UInt64? = nil) throws {
        try self.init(data: try Data(contentsOf: url), seed: seed)
    }

    /// The fitted time for a move of `dist` points.
    public func expectedDuration(_ dist: Double) -> Double {
        max(0.05, fitA + fitB * log2(1.0 + dist))
    }

    /// A recorded stroke of about this length and direction, not used lately.
    mutating func choose(dist: Double, angle: Double) -> HumanStroke {
        var scored: [(cost: Double, index: Int)] = []
        scored.reserveCapacity(strokes.count)
        for (i, s) in strokes.enumerated() {
            let turn = abs((angle - s.angle).remainder(dividingBy: 2 * Double.pi))
            let cost = abs(log(dist / s.dist)) + HumanStrokeLibrary.angleWeight * turn / (Double.pi / 2)
            scored.append((cost, i))
        }
        scored.sort { $0.cost != $1.cost ? $0.cost < $1.cost : $0.index < $1.index }
        var pool: [Int] = []
        for entry in scored where !recent.contains(strokes[entry.index].id) {
            pool.append(entry.index)
            if pool.count == HumanStrokeLibrary.choices { break }
        }
        let stroke = strokes[pool[Int(rng.unit() * Double(pool.count))]]
        // never the same stroke twice running, nor any of the last few;
        // always leave at least one stroke to choose from
        recent.append(stroke.id)
        let keep = min(HumanStrokeLibrary.recentCount, strokes.count - 1)
        recent = Array(recent[max(0, recent.count - keep)...])
        return stroke
    }

    /// Seconds to rest on the target before pressing: one of the recorded waits.
    public mutating func dwell() -> Double {
        let waits = strokes.compactMap { $0.dwell }
        if waits.isEmpty { return 0.05 }
        return waits[Int(rng.unit() * Double(waits.count))]
    }

    /// A timed path from `start` to `end`, in points. The first point is `start` at t = 0 and the
    /// last is exactly `end`. With `screen` (width, height) the path is kept on the screen.
    public mutating func path(from start: (x: Double, y: Double), to end: (x: Double, y: Double),
                              screen: (width: Double, height: Double)? = nil) -> HumanPath {
        let dx = end.x - start.x, dy = end.y - start.y
        let dist = (dx * dx + dy * dy).squareRoot()
        if dist < 0.5 || strokes.isEmpty {
            return dist > 0
                ? HumanPath(t: [0, 0], x: [start.x, end.x], y: [start.y, end.y], strokeId: -1)
                : HumanPath(t: [0], x: [start.x], y: [start.y], strokeId: -1)
        }
        let stroke = choose(dist: dist, angle: atan2(dy, dx))

        // Variety that stays inside what the hand does: a few percent on the pace, a slight
        // shift of where the speed peaks, a little more or less bow.
        let pace = rng.between(0.93, 1.09)
        let lean = rng.between(-0.10, 0.10)
        let bow = rng.between(0.85, 1.15)

        let scale = dist / stroke.dist
        // A longer or shorter reach than the recorded one takes the time the hand's own
        // distance/time law says, not a plain multiple.
        let base = expectedDuration(stroke.dist)
        var stretch = base > 0 ? expectedDuration(dist) / base : 1.0
        stretch = min(2.0, max(0.5, stretch)) * pace
        let total = stroke.t[stroke.t.count - 1]
        let cx = dx / dist, cy = dy / dist

        let n = stroke.t.count
        var ts = [Double](repeating: 0, count: n), xs = ts, ys = ts
        for i in 0..<n {
            let u = stroke.t[i] / total
            ts[i] = total * stretch * (u + lean * sin(2 * Double.pi * u) / (2 * Double.pi))
            let a = stroke.a[i] * scale
            let b = stroke.b[i] * scale * bow
            var x = start.x + a * cx - b * cy
            var y = start.y + a * cy + b * cx
            if let screen {
                x = min(max(x, 0.0), screen.width - 1.0)
                y = min(max(y, 0.0), screen.height - 1.0)
            }
            xs[i] = x
            ys[i] = y
        }
        ts[0] = 0; xs[0] = start.x; ys[0] = start.y
        xs[n - 1] = end.x; ys[n - 1] = end.y
        return HumanPath(t: ts, x: xs, y: ys, strokeId: stroke.id)
    }
}

#if canImport(CoreGraphics)
import CoreGraphics

extension HumanStrokeLibrary {
    /// The same, for CGPoint and CGSize.
    public mutating func path(from start: CGPoint, to end: CGPoint, screen: CGSize? = nil) -> HumanPath {
        path(from: (Double(start.x), Double(start.y)), to: (Double(end.x), Double(end.y)),
             screen: screen.map { (Double($0.width), Double($0.height)) })
    }
}

extension HumanPath {
    public func point(at when: Double) -> CGPoint {
        let p = position(at: when)
        return CGPoint(x: p.x, y: p.y)
    }
}
#endif
