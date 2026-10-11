/**
 * The sport catalogue, as the API defines it (backend/app/services/sports.py).
 *
 * Loaded once when the app starts, before the dashboard renders, and read
 * synchronously from then on: labels, pace or speed, cadence units, colours
 * and order all come from here rather than from lists of sport names in the
 * components. Adding a sport is a backend change only.
 */

let catalogue = []
let byKey = new Map()

/** Replace the catalogue. Called with GET /api/sports, and by the tests. */
export function setSports(sports) {
  catalogue = Array.isArray(sports) ? sports : []
  byKey = new Map(catalogue.map((sport) => [sport.key, sport]))
}

/**
 * Everything the dashboard needs to show a sport.
 *
 * A sport the catalogue does not list is one a file named that has no entry
 * yet — the backend keeps "rowing" as "rowing" rather than calling it other.
 * It reads by speed, in the "other" colour, under its own name.
 */
export function sportInfo(key) {
  const known = byKey.get(key)
  if (known) return known
  return {
    key,
    label: key ? key.charAt(0).toUpperCase() + key.slice(1) : 'Other',
    rate: 'speed',
    cadence_unit: 'rpm',
    color: 'other',
    has_distance: true,
  }
}

/**
 * Whether the sport goes anywhere. Strength does not: its distance, pace,
 * climb and route are left out rather than shown as zeros.
 */
export function hasDistance(key) {
  return sportInfo(key).has_distance !== false
}

/** Sort key for display order. Sports the catalogue does not list go last. */
export function sportRank(key) {
  const index = catalogue.findIndex((sport) => sport.key === key)
  return index === -1 ? catalogue.length : index
}
