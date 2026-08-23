/**
 * Measuring a track: how far in, how long in, and how fast at each sample.
 *
 * Shared because two things need it — the route drawing and the comparison
 * between two activities — and two copies of "what counts as a plausible
 * speed" would drift apart.
 */

import { haversineDistance } from './geo'

/**
 * Above this a "speed" is a GPS artefact, not movement (m/s, ≈ 120 km/h).
 *
 * Deliberately a speed and not a distance: samples arrive downsampled, so
 * consecutive ones can be hundreds of metres apart quite legitimately, and a
 * distance ceiling would throw away real riding at a high stride.
 */
const IMPLAUSIBLE_SPEED_MS = 120_000 / 3_600

/**
 * Cumulative metres and seconds along a track, and the speed of each hop.
 *
 * There is one fewer speed than there are samples: `speeds[i]` belongs to the
 * hop arriving at sample i + 1. A sample with no timestamp contributes distance
 * but no time, so the clock holds rather than jumping.
 */
export function measureTrack(samples) {
  const distances = [0]
  const elapsed = [0]
  const speeds = []
  if (!samples?.length) return { distances: [], elapsed: [], speeds: [] }

  const first = samples[0].timestamp
  const start = first ? new Date(first).getTime() : null

  for (let index = 1; index < samples.length; index += 1) {
    const from = samples[index - 1]
    const to = samples[index]
    const metres = haversineDistance(from.latitude, from.longitude, to.latitude, to.longitude)
    distances.push(distances[index - 1] + metres)

    if (start == null || !to.timestamp) {
      elapsed.push(elapsed[index - 1])
      speeds.push(null)
      continue
    }
    elapsed.push((new Date(to.timestamp).getTime() - start) / 1000)
    const seconds = elapsed[index] - elapsed[index - 1]
    const speed = seconds > 0 ? metres / seconds : null
    speeds.push(speed != null && speed <= IMPLAUSIBLE_SPEED_MS ? speed : null)
  }

  return { distances, elapsed, speeds }
}

/**
 * Speed and elevation against distance travelled, ready to plot.
 *
 * Distance rather than elapsed time is the axis two activities can share: run
 * the same route a minute slower and a time axis pulls the two apart from the
 * first hill, while a distance axis keeps the hill in the same place.
 *
 * The speed at a sample is the hop that arrived there; the first sample has no
 * hop behind it and takes the one that leaves it, so the series starts at zero
 * distance rather than at the second point.
 */
export function distanceSeries(samples) {
  const located = (samples ?? []).filter(
    (sample) => sample.latitude != null && sample.longitude != null,
  )
  if (located.length < 2) return []

  const { distances, speeds } = measureTrack(located)
  return located.map((sample, index) => ({
    distance: distances[index],
    speed: speeds[index - 1] ?? speeds[index] ?? null,
    elevation: sample.elevation ?? null,
  }))
}

/** How many points a comparison grid gets. More than any chart has pixels for. */
const GRID_POINTS = 240

/**
 * Two or more distance series resampled onto one shared grid.
 *
 * Merging two tracks' own samples into shared rows does not work: each row
 * carries a value for one activity and a gap for the other, so a chart that
 * does not bridge gaps draws both lines shattered into invisible fragments
 * wherever they overlap — which is exactly the range you wanted to compare.
 *
 * Resampling instead puts a value for every activity at every grid distance, by
 * interpolating between the samples either side. Past the end of a shorter
 * activity the value is null, so its line stops rather than being stretched to
 * the length of the longer one.
 */
export function sharedGrid(seriesList, dataKey, points = GRID_POINTS) {
  const usable = seriesList.map((entry) =>
    entry.points.filter((point) => point[dataKey] != null),
  )
  const furthest = Math.max(0, ...usable.flat().map((point) => point.distance))
  if (!furthest) return []

  const step = furthest / (points - 1)
  return Array.from({ length: points }, (_, index) => {
    const distance = index * step
    const row = { distance }
    usable.forEach((entryPoints, series) => {
      const value = interpolate(entryPoints, distance, dataKey)
      if (value != null) row[`v${series}`] = value
    })
    return row
  })
}

/** The value at `distance`, straight-line between the samples either side. */
function interpolate(points, distance, dataKey) {
  if (points.length < 2) return null
  if (distance < points[0].distance || distance > points[points.length - 1].distance) return null

  // The samples are already in distance order, so walk to the bracketing pair.
  let high = 1
  while (high < points.length - 1 && points[high].distance < distance) high += 1
  const before = points[high - 1]
  const after = points[high]
  const span = after.distance - before.distance
  if (span <= 0) return after[dataKey]
  const fraction = (distance - before.distance) / span
  return before[dataKey] + (after[dataKey] - before[dataKey]) * fraction
}
