import { hasDistance } from '../sports'
import { sportColor } from '../theme'
import { useColorScheme } from '../hooks/useColorScheme'
import {
  formatDate,
  formatDistance,
  formatDuration,
  formatElevation,
  formatPaceOrSpeed,
  sportLabel,
} from '../utils/formatters'

/**
 * Per-sport records: the biggest activities, and the fastest standard distances.
 *
 * Every record names the activity that holds it and when, because a figure
 * with nothing behind it cannot be checked — and because the usual next
 * question is "which ride was that".
 */
export default function Records({ bySport, onOpenWorkout }) {
  const dark = useColorScheme()

  if (!bySport?.length) {
    return (
      <section className="panel p-6 text-center" aria-labelledby="records-heading">
        <h2 id="records-heading" className="sr-only">
          Records
        </h2>
        <p className="text-sm muted">
          No records yet. They appear once there is something to compare.
        </p>
      </section>
    )
  }

  return (
    <section className="panel p-4" aria-labelledby="records-heading">
      <h2 id="records-heading" className="text-sm font-semibold">
        Records
      </h2>

      <div className="mt-4 space-y-6">
        {bySport.map((sport) => (
          <SportBlock
            key={sport.sport_type}
            sport={sport}
            dark={dark}
            onOpenWorkout={onOpenWorkout}
          />
        ))}
      </div>
    </section>
  )
}

function SportBlock({ sport, dark, onOpenWorkout }) {
  // "Furthest" rather than "Longest": next to "Longest time" it would not be
  // clear which of the two the number measures.
  // A sport that goes nowhere has one record worth the name: how long.
  const moves = hasDistance(sport.sport_type)
  const biggest = [
    moves && ['Furthest', sport.longest_distance, (value) => formatDistance(value)],
    ['Longest time', sport.longest_duration, (value) => formatDuration(value)],
    moves && ['Biggest climb', sport.biggest_climb, (value) => formatElevation(value)],
  ].filter(Boolean)

  return (
    <div>
      <h3 className="text-xs font-semibold uppercase tracking-wide">
        <span
          aria-hidden="true"
          className="mr-2 inline-block h-2 w-2 rounded-full align-middle"
          style={{ backgroundColor: sportColor(sport.sport_type, dark) }}
        />
        {sportLabel(sport.sport_type)}
        <span className="ml-2 font-normal muted">{sport.workout_count}×</span>
      </h3>

      <dl className="mt-2 grid grid-cols-1 gap-3 text-sm sm:grid-cols-3">
        {biggest.map(([label, holder, format]) => (
          <div key={label}>
            <dt className="text-xs uppercase tracking-wide muted">{label}</dt>
            <dd className="tabular-nums">
              {holder ? format(holder.value) : '—'}
              {holder && (
                <Attribution holder={holder} onOpenWorkout={onOpenWorkout} />
              )}
            </dd>
          </div>
        ))}
      </dl>

      {moves && sport.distance_bests.length > 0 && (
        <div className="mt-3 table-scroll">
          <table className="w-full text-sm">
            <caption className="sr-only">
              Fastest standard distances for {sportLabel(sport.sport_type)}
            </caption>
            <thead className="muted border-y border-[var(--border)] text-left text-xs uppercase tracking-wide">
              <tr>
                <th scope="col" className="py-1 pr-2 font-medium sm:pr-4">Distance</th>
                <th scope="col" className="py-1 pr-2 text-right font-medium sm:pr-4">Time</th>
                <th scope="col" className="py-1 pr-2 text-right font-medium sm:pr-4">Pace</th>
                <th scope="col" className="py-1 font-medium">Set on</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-[var(--border)]">
              {sport.distance_bests.map((best) => (
                <tr key={best.distance_m}>
                  <td className="whitespace-nowrap py-1 pr-2 sm:pr-4">{best.label}</td>
                  <td className="py-1 pr-2 text-right tabular-nums sm:pr-4">
                    {formatDuration(best.duration_s)}
                  </td>
                  <td className="whitespace-nowrap py-1 pr-2 text-right tabular-nums sm:pr-4">
                    {formatPaceOrSpeed(sport.sport_type, best.distance_m, best.duration_s)}
                  </td>
                  <td className="py-1">
                    <Attribution holder={best} onOpenWorkout={onOpenWorkout} inline />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}

/** Which activity holds this, and when — as a link when it can be opened. */
function Attribution({ holder, onOpenWorkout, inline = false }) {
  const when = formatDate(holder.start_time)
  const label = `${holder.workout_name} · ${when}`

  if (!onOpenWorkout) {
    return <span className={inline ? 'text-xs muted' : 'block text-xs muted'}>{label}</span>
  }

  return (
    <button
      type="button"
      onClick={() => onOpenWorkout(holder.workout_id)}
      className={`${inline ? '' : 'block '}text-left text-xs text-sky-700 hover:underline dark:text-sky-400`}
    >
      {label}
    </button>
  )
}
