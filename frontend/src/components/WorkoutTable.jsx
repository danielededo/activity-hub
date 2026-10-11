import { useState } from 'react'
import { hasDistance } from '../sports'
import { sportColor } from '../theme'
import { useColorScheme } from '../hooks/useColorScheme'
import {
  formatDate,
  formatDistance,
  formatDuration,
  formatElevation,
  formatHeartRate,
  formatLocalTime,
  formatPaceOrSpeed,
  sportLabel,
} from '../utils/formatters'

/**
 * Padding, tighter on a phone. Nine columns at px-4 need 788px of table, which
 * is more than a phone has and — because the widest column set holds the whole
 * layout open — dragged the entire page sideways rather than just the table.
 */
const CELL = 'px-2 py-2 sm:px-4'

/**
 * Which columns a screen has room for.
 *
 * Dropped rather than scrolled. A scroll container keeps the page still, which
 * this table already had, but nine columns behind a 356px window is a reader
 * swiping to find a number they cannot see; three columns they can read is
 * better than nine they cannot. Everything hidden here is still in the CSV
 * export and in the activity itself.
 */
const SPORT_COL = 'hidden sm:table-cell'
const TIME_COL = 'hidden sm:table-cell'
const PACE_COL = 'hidden md:table-cell'
const WIDE_COL = 'hidden lg:table-cell'

/** The table view: every activity, in numbers, not colour. */
export default function WorkoutTable({
  workouts,
  total,
  limit,
  offset,
  onPage,
  onOpen,
  onDelete,
  filtered = false,
}) {
  const dark = useColorScheme()
  // Which row has been asked to be deleted and is waiting for a confirmation.
  const [confirming, setConfirming] = useState(null)

  if (!workouts?.length) {
    return (
      <section className="panel p-6 text-center">
        <p className="text-sm muted">
          {filtered
            ? 'No activities match these filters.'
            : 'No activities yet. Upload a FIT, TCX or GPX file to get started.'}
        </p>
      </section>
    )
  }

  const from = offset + 1
  const to = Math.min(offset + workouts.length, total)

  return (
    <section
      className="panel"
      aria-labelledby="workouts-heading"
    >
      <div className="flex items-baseline justify-between p-4">
        <h2 id="workouts-heading" className="text-sm font-semibold">
          Activities
        </h2>
        <p className="text-xs muted">
          {from}–{to} of {total}
        </p>
      </div>

      <div className="table-scroll">
        <table className="w-full text-sm">
          <thead className="muted border-y border-[var(--border)] text-left text-xs uppercase tracking-wide">
            <tr>
              <th scope="col" className={CELL + ' font-medium'}>Date</th>
              <th scope="col" className={CELL + ' font-medium'}>Activity</th>
              <th scope="col" className={`${SPORT_COL} ${CELL} font-medium`}>Sport</th>
              <th scope="col" className={CELL + ' text-right font-medium'}>Distance</th>
              <th scope="col" className={`${TIME_COL} ${CELL} text-right font-medium`}>Time</th>
              <th scope="col" className={`${PACE_COL} ${CELL} text-right font-medium`}>Pace</th>
              <th scope="col" className={`${WIDE_COL} ${CELL} text-right font-medium`}>Climb</th>
              <th scope="col" className={`${WIDE_COL} ${CELL} text-right font-medium`}>HR</th>
              {/* Pinned: the confirmation is wider than the Delete button it
                  replaces, and without a fixed width every column shifts
                  sideways the moment somebody arms a delete. */}
              <th scope="col" className={`w-20 sm:w-32 ${CELL}`}>
                <span className="sr-only">Actions</span>
              </th>
            </tr>
          </thead>
          <tbody className="divide-y divide-[var(--border)]">
            {workouts.map((workout) => (
              <tr key={workout.id} className="hover:bg-[var(--surface-sunken)]">
                <td className={`whitespace-nowrap ${CELL} tabular-nums`}>
                  {formatDate(workout.start_time)}
                  {/* Under the date on a phone, beside it once there is room:
                      the two on one line made this the widest column in the
                      table, at 133px of a 286px window. */}
                  <span className="block text-xs muted sm:ml-1 sm:inline">
                    {formatLocalTime(workout.start_time, workout.utc_offset_minutes)}
                  </span>
                </td>
                <td className={CELL}>
                  <button
                    type="button"
                    onClick={() => onOpen(workout)}
                    className="text-left font-medium text-sky-700 hover:underline dark:text-sky-400"
                  >
                    {/* The dot rides here only while the Sport column is
                        hidden, so a narrow screen still says which sport this
                        was instead of dropping the fact entirely. */}
                    <span
                      aria-hidden="true"
                      className="mr-1.5 inline-block h-2 w-2 rounded-full align-middle sm:hidden"
                      style={{ backgroundColor: sportColor(workout.sport_type, dark) }}
                    />
                    {workout.name}
                  </button>
                  <span className="sr-only sm:hidden"> · {sportLabel(workout.sport_type)}</span>
                </td>
                <td className={`${SPORT_COL} whitespace-nowrap ${CELL}`}>
                  <span
                    aria-hidden="true"
                    className="mr-2 inline-block h-2 w-2 rounded-full align-middle"
                    style={{ backgroundColor: sportColor(workout.sport_type, dark) }}
                  />
                  {sportLabel(workout.sport_type)}
                </td>
                <td className={`${CELL} text-right tabular-nums`}>
                  {hasDistance(workout.sport_type) ? formatDistance(workout.total_distance) : '—'}
                </td>
                <td className={`${TIME_COL} ${CELL} text-right tabular-nums`}>
                  {formatDuration(workout.total_time)}
                </td>
                <td className={`${PACE_COL} whitespace-nowrap ${CELL} text-right tabular-nums`}>
                  {formatPaceOrSpeed(workout.sport_type, workout.total_distance, workout.total_time)}
                </td>
                <td className={`${WIDE_COL} ${CELL} text-right tabular-nums`}>
                  {hasDistance(workout.sport_type)
                    ? formatElevation(workout.total_elevation_gain)
                    : '—'}
                </td>
                <td className={`${WIDE_COL} ${CELL} text-right tabular-nums`}>
                  {formatHeartRate(workout.avg_heart_rate)}
                </td>
                <td className={`whitespace-nowrap ${CELL} text-right`}>
                  {confirming === workout.id ? (
                    // Deleting takes the track points with it and there is no
                    // undo, so the destructive click is the second one.
                    //
                    // Cancel comes second on purpose: it lands where the
                    // Delete button just was, so a double-click cancels
                    // instead of deleting. Do not reorder these two.
                    <span className="inline-flex items-center gap-2">
                      <button
                        type="button"
                        onClick={() => {
                          setConfirming(null)
                          onDelete(workout)
                        }}
                        aria-label={`Confirm deleting ${workout.name}`}
                        className="text-xs font-medium text-red-700 dark:text-red-400"
                      >
                        Delete
                      </button>
                      <button
                        type="button"
                        onClick={() => setConfirming(null)}
                        aria-label={`Keep ${workout.name}`}
                        className="muted text-xs"
                      >
                        Cancel
                      </button>
                    </span>
                  ) : (
                    <button
                      type="button"
                      onClick={() => setConfirming(workout.id)}
                      aria-label={`Delete ${workout.name}`}
                      className="muted text-xs hover:text-red-700 dark:hover:text-red-400"
                    >
                      Delete
                    </button>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {total > limit && (
        <div className="flex items-center justify-between p-4">
          <button
            type="button"
            disabled={offset === 0}
            onClick={() => onPage(Math.max(0, offset - limit))}
            className="rounded-md border border-[var(--border)] px-3 py-1 text-sm disabled:opacity-40"
          >
            Previous
          </button>
          <button
            type="button"
            disabled={offset + limit >= total}
            onClick={() => onPage(offset + limit)}
            className="rounded-md border border-[var(--border)] px-3 py-1 text-sm disabled:opacity-40"
          >
            Next
          </button>
        </div>
      )}
    </section>
  )
}
