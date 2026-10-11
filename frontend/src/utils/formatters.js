/**
 * Metric formatting. The API is metric and so is the UI — no unit toggle.
 *
 * Runners read minutes per kilometre and cyclists read kilometres per hour, so
 * the pace helper picks by sport rather than showing one and making the other
 * do arithmetic. Which sport reads which way is the sport catalogue's to say.
 */

import { hasDistance, sportInfo } from '../sports'

const readsAsPace = (sportType) => sportInfo(sportType).rate === 'pace'

export function formatDistance(metres) {
  if (metres == null) return '—'
  if (metres < 1000) return `${Math.round(metres)} m`
  return `${(metres / 1000).toFixed(1)} km`
}

export function formatDuration(seconds) {
  if (seconds == null || seconds <= 0) return '—'
  const total = Math.round(seconds)
  const hours = Math.floor(total / 3600)
  const minutes = Math.floor((total % 3600) / 60)
  if (hours > 0) return `${hours}h ${String(minutes).padStart(2, '0')}m`
  return `${minutes}m ${String(total % 60).padStart(2, '0')}s`
}

/**
 * A position on an elapsed-time axis.
 *
 * formatDuration answers "—" for zero, which is right for a duration nobody
 * recorded and wrong for the origin of an axis: the first tick of every trace
 * was rendering as a dash.
 */
export function formatElapsed(seconds) {
  if (seconds == null) return '—'
  return seconds <= 0 ? '0s' : formatDuration(seconds)
}

/**
 * A duration short enough for an axis tick.
 *
 * formatDuration spells out seconds — "55m 00s" — which is right in a table and
 * too long beside a y axis, where a label wider than the axis is silently
 * clipped and reads as a different number.
 */
export function formatShortDuration(seconds) {
  if (seconds == null || seconds <= 0) return '0'
  const minutes = Math.round(seconds / 60)
  const hours = Math.floor(minutes / 60)
  return hours ? `${hours}h ${String(minutes % 60).padStart(2, '0')}m` : `${minutes}m`
}

export function formatElevation(metres) {
  if (metres == null) return '—'
  return `${Math.round(metres)} m`
}

export function formatHeartRate(bpm) {
  return bpm == null ? '—' : `${Math.round(bpm)} bpm`
}

/**
 * What a cadence figure is counted in, for this sport.
 *
 * Cyclists count crank revolutions. On foot, TCX `RunCadence` and GPX `cad`
 * are written per leg by Garmin, Strava and Komoot alike, so the figure is
 * strides per minute — roughly half the steps-per-minute a watch displays.
 * It is reported as recorded rather than doubled: an exporter that already
 * counts both feet would then read twice as fast as the run actually was, and
 * nothing in either format says which convention a file used.
 */
export function cadenceUnit(sportType) {
  return sportInfo(sportType).cadence_unit
}

export function formatCadence(value, sportType) {
  return value == null ? '—' : `${Math.round(value)} ${cadenceUnit(sportType)}`
}

/**
 * Minutes per kilometre for foot sports, km/h for everything else, and nothing
 * for a sport that goes nowhere — even if its watch logged a few metres.
 */
export function formatPaceOrSpeed(sportType, metres, seconds) {
  if (!metres || !seconds || !hasDistance(sportType)) return '—'
  if (readsAsPace(sportType)) {
    const secondsPerKm = seconds / (metres / 1000)
    const minutes = Math.floor(secondsPerKm / 60)
    const rest = Math.round(secondsPerKm % 60)
    // 4:60 /km is not a pace anybody writes.
    const carried = rest === 60 ? [minutes + 1, 0] : [minutes, rest]
    return `${carried[0]}:${String(carried[1]).padStart(2, '0')} /km`
  }
  return `${(metres / seconds * 3.6).toFixed(1)} km/h`
}

/**
 * A rate in metres per second, as the pace or speed the sport reads in.
 *
 * Delegates rather than repeating the arithmetic: a rate is a distance over one
 * second, so the same helper that formats a whole activity formats an instant.
 */
export function formatRate(sportType, metresPerSecond) {
  if (!metresPerSecond) return '—'
  return formatPaceOrSpeed(sportType, metresPerSecond, 1)
}

/**
 * An instantaneous speed, in km/h whatever the sport.
 *
 * Deliberately not pace, even for the sports that read in minutes per
 * kilometre. A whole activity always moved, so its pace is a number; a single
 * sample often did not, and the pace of a standstill is unbounded — the zero
 * tick of a pace axis rendered as a dash and the ones above it ran 11:54, 5:57,
 * 3:58, faster as they climbed. Speed is linear, starts at zero and rises the
 * way an axis is read. Pace stays where it is well defined: the summary of the
 * activity as a whole.
 */
export function formatSpeed(metresPerSecond) {
  if (metresPerSecond == null) return '—'
  return `${(metresPerSecond * 3.6).toFixed(1)} km/h`
}

/**
 * A training-load figure, rounded, with an explicit sign when it can be either.
 *
 * Form is the only figure here that goes negative, and "-8" against "8" is a
 * difference a reader can miss; "+8" against "-8" is not. Zero gets no sign.
 */
export function formatSigned(value) {
  if (value == null) return '—'
  const rounded = Math.round(value)
  return rounded > 0 ? `+${rounded}` : String(rounded)
}

export function formatDate(iso) {
  if (!iso) return '—'
  return new Date(iso).toLocaleDateString(undefined, {
    day: '2-digit',
    month: 'short',
    year: 'numeric',
  })
}

/**
 * The activity's own local time, using the offset its file stated.
 *
 * Always 24-hour HH:MM. Falling back to the viewer's locale for the no-offset
 * case put "06:45 PM" and "08:45" in the same column, which reads as two
 * different kinds of number rather than two activities.
 */
export function formatLocalTime(iso, utcOffsetMinutes) {
  if (!iso) return '—'
  const moment = new Date(iso)
  const stated = utcOffsetMinutes != null
  const shifted = stated ? new Date(moment.getTime() + utcOffsetMinutes * 60_000) : moment
  const hours = stated ? shifted.getUTCHours() : shifted.getHours()
  const minutes = stated ? shifted.getUTCMinutes() : shifted.getMinutes()
  return `${String(hours).padStart(2, '0')}:${String(minutes).padStart(2, '0')}`
}

export function sportLabel(sportType) {
  return sportInfo(sportType).label
}

/**
 * A month and year, for an axis whose window is longer than a year.
 *
 * formatWeek drops the year, which is right on a twelve-week chart and wrong on
 * a twelve-month one: a year of days ran from "Aug 22" to "Aug 21", two labels
 * that read as the same fortnight rather than as a year apart.
 */
export function formatMonth(iso) {
  if (!iso) return '—'
  return new Date(iso).toLocaleDateString(undefined, { month: 'short', year: 'numeric' })
}

export function formatWeek(weekStart) {
  return new Date(weekStart).toLocaleDateString(undefined, { day: '2-digit', month: 'short' })
}
