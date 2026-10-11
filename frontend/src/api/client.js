/** Everything this app knows how to ask the API. */

import axios from 'axios'

// Empty base URL means /api on the app's own origin — what the Vite dev proxy
// and the nginx image both serve, so no CORS is involved either way.
const baseURL = `${import.meta.env.VITE_API_BASE_URL ?? ''}/api`

export const http = axios.create({ baseURL, timeout: 30_000 })

/** The API's `detail` if it sent one, so the UI can show the real reason. */
export function errorMessage(error, fallback = 'Something went wrong') {
  return error?.response?.data?.detail ?? error?.message ?? fallback
}

/** The profile, or null when nobody has introduced themselves yet. */
export async function fetchProfile() {
  try {
    const { data } = await http.get('/users/me')
    return data
  } catch (error) {
    if (error?.response?.status === 404) return null
    throw error
  }
}

export async function createProfile({ firstName, lastName }) {
  const { data } = await http.post('/users/', {
    first_name: firstName,
    last_name: lastName || null,
  })
  return data
}

/**
 * A page of activities, narrowed by whatever filters are set.
 *
 * Empty filter values are dropped rather than sent as blanks: `sport_type=`
 * would be a filter for the sport named "", which matches nothing.
 */
export async function fetchWorkouts({
  userId,
  limit = 20,
  offset = 0,
  sportType,
  dateFrom,
  dateTo,
  q,
}) {
  const { data } = await http.get('/workouts', {
    params: {
      user_id: userId,
      limit,
      offset,
      sport_type: sportType || undefined,
      date_from: dateFrom || undefined,
      date_to: dateTo || undefined,
      q: q || undefined,
    },
  })
  return data
}

export async function fetchWorkout(workoutId, userId) {
  const { data } = await http.get(`/workouts/${workoutId}`, { params: { user_id: userId } })
  return data
}

export async function fetchTrackPoints(workoutId, userId, maxPoints = 600) {
  const { data } = await http.get(`/workouts/${workoutId}/track-points`, {
    params: { user_id: userId, max_points: maxPoints },
  })
  return data
}

export async function deleteWorkout(workoutId, userId) {
  await http.delete(`/workouts/${workoutId}`, { params: { user_id: userId } })
}

export async function fetchAnalysis(userId) {
  const { data } = await http.get(`/analysis/${userId}`)
  return data
}

/** Per-sport records and standard-distance bests, plus totals by year. */
export async function fetchRecords(userId) {
  const { data } = await http.get(`/analysis/${userId}/records`)
  return data
}

/** Time in each heart-rate zone, lifetime and by week, with training load. */
export async function fetchZones(userId, weeks = 12) {
  const { data } = await http.get(`/analysis/${userId}/zones`, { params: { weeks } })
  return data
}

/** Fitness, fatigue and form, one entry per calendar day. */
export async function fetchForm(userId, days = 90) {
  const { data } = await http.get(`/analysis/${userId}/form`, { params: { days } })
  return data
}

/** One activity's time in zone. Empty when it recorded no heart rate. */
export async function fetchWorkoutZones(workoutId, userId) {
  const { data } = await http.get(`/workouts/${workoutId}/zones`, { params: { user_id: userId } })
  return data
}

export async function fetchWeekly(userId, weeks = 12) {
  const { data } = await http.get(`/analysis/${userId}/weekly`, { params: { weeks } })
  return data
}

/**
 * The URL a download link should point at.
 *
 * Built rather than fetched: letting the browser follow a link is what makes
 * the file land in the downloads folder with the name the server chose. Fetching
 * it into memory and handing it to a blob URL would work too, and would break
 * on a library big enough to matter.
 */
export function exportUrl(path, { userId, sportType, dateFrom, dateTo, q } = {}) {
  const params = new URLSearchParams({ user_id: String(userId) })
  if (sportType) params.set('sport_type', sportType)
  if (dateFrom) params.set('date_from', dateFrom)
  if (dateTo) params.set('date_to', dateTo)
  if (q) params.set('q', q)
  return `${baseURL}${path}?${params}`
}

export async function uploadWorkout(userId, file) {
  const body = new FormData()
  body.append('file', file)
  const { data } = await http.post('/upload', body, { params: { user_id: userId } })
  return data
}

/**
 * Send an export archive. Answered as soon as it is accepted, with an import
 * that is still running: follow it with fetchArchiveImport.
 */
export async function uploadArchive(userId, file) {
  const body = new FormData()
  body.append('file', file)
  const { data } = await http.post('/upload/archive', body, {
    params: { user_id: userId },
    // Only the transfer now — the import happens after the answer — but a
    // 200 MB export over a slow uplink still takes a while to send.
    timeout: 10 * 60_000,
  })
  return data
}

/** Where an archive import has got to: counts so far, or how it ended. */
export async function fetchArchiveImport(userId, importId) {
  const { data } = await http.get(`/upload/archive/${importId}`, {
    params: { user_id: userId },
  })
  return data
}
