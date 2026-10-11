import { render, screen, within } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import Records from '../src/components/Records'
import SportBreakdown from '../src/components/SportBreakdown'
import WorkoutDetail from '../src/components/WorkoutDetail'
import WorkoutTable from '../src/components/WorkoutTable'
import * as api from '../src/api/client'
import { formatPaceOrSpeed } from '../src/utils/formatters'

vi.mock('../src/api/client', async (importOriginal) =>
  (await import('./mockClient')).mockClient(importOriginal),
)

/**
 * A strength session as a Garmin records one: no position, heart rate only,
 * and the few metres of distance a wrist accelerometer invents in a gym.
 */
const GYM = {
  id: 5,
  name: 'Strength 2026-06-24',
  sport_type: 'strength',
  source: 'garmin',
  file_format: 'fit',
  start_time: '2026-06-24T17:00:00Z',
  utc_offset_minutes: 120,
  total_distance: 35,
  total_time: 2_700,
  total_elevation_gain: 4,
  avg_heart_rate: 112,
  avg_cadence: null,
}

const holder = (value) => ({
  workout_id: 5,
  workout_name: 'Strength 2026-06-24',
  start_time: '2026-06-24T17:00:00Z',
  utc_offset_minutes: 120,
  value,
})

beforeEach(() => {
  vi.clearAllMocks()
  api.fetchTrackPoints.mockResolvedValue({
    workout_id: 5,
    total: 3,
    returned: 3,
    stride: 1,
    items: [0, 1, 2].map((index) => ({
      sequence: index,
      timestamp: new Date(Date.UTC(2026, 5, 24, 17, index)).toISOString(),
      latitude: null,
      longitude: null,
      elevation: null,
      heart_rate: 100 + index * 10,
      cadence: null,
    })),
  })
})

describe('a sport without distance', () => {
  it('has no pace, whatever its watch logged', () => {
    expect(formatPaceOrSpeed('strength', 35, 2_700)).toBe('—')
  })

  it('shows time and heart rate in the detail, not distance, pace, climb or a route', async () => {
    render(<WorkoutDetail workout={GYM} userId={1} onClose={vi.fn()} />)

    expect(await screen.findByRole('heading', { name: 'Heart rate' })).toBeVisible()
    const figures = screen.getAllByRole('term')[0].closest('dl')
    const labels = within(figures).getAllByRole('term').map((term) => term.textContent)
    expect(labels).toEqual(['Time', 'Heart rate', 'Cadence'])
    expect(screen.queryByRole('heading', { name: 'Route' })).not.toBeInTheDocument()
  })

  it('offers no comparison along a distance axis', async () => {
    render(<WorkoutDetail workout={GYM} userId={1} onClose={vi.fn()} />)

    await screen.findByRole('heading', { name: 'Heart rate' })
    expect(api.fetchWorkouts).not.toHaveBeenCalled()
  })

  it('shows dashes in the table for distance, pace and climb', () => {
    render(
      <WorkoutTable
        workouts={[GYM]}
        total={1}
        limit={20}
        offset={0}
        onPage={vi.fn()}
        onOpen={vi.fn()}
        onDelete={vi.fn()}
      />,
    )

    expect(screen.queryByText('35 m')).not.toBeInTheDocument()
    expect(screen.queryByText('4 m')).not.toBeInTheDocument()
    expect(screen.getByText('45m 00s')).toBeInTheDocument()
  })

  it('keeps only the longest session among its records', () => {
    render(
      <Records
        bySport={[
          {
            sport_type: 'strength',
            workout_count: 3,
            longest_distance: holder(35),
            longest_duration: holder(2_700),
            biggest_climb: holder(4),
            distance_bests: [],
          },
        ]}
        onOpenWorkout={vi.fn()}
      />,
    )

    expect(screen.getByText('Longest time')).toBeInTheDocument()
    expect(screen.queryByText('Furthest')).not.toBeInTheDocument()
    expect(screen.queryByText('Biggest climb')).not.toBeInTheDocument()
  })

  it('is listed by sport with its time and count, but no distance bar', () => {
    const { container } = render(
      <SportBreakdown
        bySport={[
          { sport_type: 'running', workout_count: 4, total_distance: 40_000, total_time: 14_400 },
          { sport_type: 'strength', workout_count: 3, total_distance: 35, total_time: 8_100 },
        ]}
      />,
    )

    const strength = screen.getByText('Strength').closest('li')
    expect(within(strength).getByText('3×')).toBeInTheDocument()
    expect(within(strength).getByText('2h 15m')).toBeInTheDocument()
    expect(within(strength).queryByText(/35 m/)).not.toBeInTheDocument()
    // One bar, for running; a sliver for strength would claim a distance.
    expect(container.querySelectorAll('li [style*="width"]')).toHaveLength(1)
  })
})
