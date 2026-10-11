import { sportRank } from '../sports'
import { sportColor } from '../theme'
import { useColorScheme } from '../hooks/useColorScheme'
import { formatDistance, formatDuration, sportLabel } from '../utils/formatters'

/**
 * Distance per sport, as bars in the palette's fixed slot order.
 *
 * Every bar carries its own label and value: two of the light-mode hues sit
 * below 3:1 against white, so identity is never left to colour alone.
 */
export default function SportBreakdown({ bySport }) {
  const dark = useColorScheme()
  if (!bySport?.length) return null

  const ordered = [...bySport].sort(
    (a, b) => sportRank(a.sport_type) - sportRank(b.sport_type),
  )
  const longest = Math.max(...ordered.map((row) => row.total_distance), 1)

  return (
    <section
      className="panel p-4"
      aria-labelledby="by-sport-heading"
    >
      <h2 id="by-sport-heading" className="text-sm font-semibold">
        Distance by sport
      </h2>

      <ul className="mt-4 space-y-3">
        {ordered.map((row) => (
          <li key={row.sport_type}>
            <div className="flex items-baseline justify-between text-sm">
              <span className="font-medium">{sportLabel(row.sport_type)}</span>
              <span className="tabular-nums muted">
                {formatDistance(row.total_distance)} · {row.workout_count}×
              </span>
            </div>
            <div className="mt-1 h-2 w-full overflow-hidden rounded-full bg-[var(--surface-sunken)]">
              <div
                className="h-full rounded-full"
                style={{
                  width: `${Math.max(2, (row.total_distance / longest) * 100)}%`,
                  backgroundColor: sportColor(row.sport_type, dark),
                }}
              />
            </div>
            <p className="mt-1 text-xs muted">
              {formatDuration(row.total_time)}
            </p>
          </li>
        ))}
      </ul>
    </section>
  )
}
