import { describe, expect, it } from 'vitest'
import { setSports, sportInfo, sportRank } from '../src/sports'
import { palette, sportColor } from '../src/theme'
import { cadenceUnit, formatPaceOrSpeed, sportLabel } from '../src/utils/formatters'
import sports from './sports.json'

describe('the sport catalogue', () => {
  it('describes a listed sport as the API does', () => {
    expect(sportInfo('hiking')).toEqual(sports.find((sport) => sport.key === 'hiking'))
  })

  it('reads a sport it does not list by speed, in the other colour, under its own name', () => {
    // The backend keeps "rowing" as "rowing" rather than calling it other.
    expect(sportInfo('rowing')).toEqual({
      key: 'rowing',
      label: 'Rowing',
      rate: 'speed',
      cadence_unit: 'rpm',
      color: 'other',
      has_distance: true,
    })
    expect(sportColor('rowing')).toBe(palette().other)
  })

  it('calls a missing sport Other', () => {
    expect(sportLabel(null)).toBe('Other')
  })

  it('orders sports as the catalogue does, unlisted ones last', () => {
    const keys = sports.map((sport) => sport.key)
    const shuffled = ['rowing', ...keys].reverse()

    expect(shuffled.sort((a, b) => sportRank(a) - sportRank(b))).toEqual([...keys, 'rowing'])
  })

  it('survives a catalogue that never arrived', () => {
    setSports(undefined)

    expect(sportLabel('running')).toBe('Running')
    expect(formatPaceOrSpeed('running', 10_000, 3600)).toBe('10.0 km/h')
  })
})

describe('adding a sport', () => {
  it('needs nothing but a catalogue entry', () => {
    // What adding a sport to backend/app/services/sports.py amounts to here.
    setSports([
      ...sports,
      { key: 'rowing', label: 'Rowing', rate: 'pace', cadence_unit: 'spm', color: 'hiking' },
    ])

    expect(sportLabel('rowing')).toBe('Rowing')
    expect(formatPaceOrSpeed('rowing', 2_000, 480)).toBe('4:00 /km')
    expect(cadenceUnit('rowing')).toBe('spm')
    expect(sportColor('rowing')).toBe(palette().hiking)
    expect(sportRank('rowing')).toBe(sports.length)
  })
})
