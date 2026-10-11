import { describe, expect, it } from 'vitest'
import { PALETTE_SLOTS, palette, seriesColors, sportColor } from '../src/theme'

describe('the sport palette', () => {
  it('keeps a fixed slot order', () => {
    // Colour follows the entity, so this order must not drift: a reorder
    // would repaint every existing chart and break the validated pairings.
    expect(PALETTE_SLOTS).toEqual(['cycling', 'running', 'hiking', 'other'])
  })

  it('gives every sport in the order its own hue', () => {
    const hues = PALETTE_SLOTS.map((sport) => sportColor(sport))
    expect(new Set(hues).size).toBe(PALETTE_SLOTS.length)
  })

  it('falls back to the "other" slot instead of inventing a hue', () => {
    expect(sportColor('kitesurfing')).toBe(palette().other)
    expect(sportColor(undefined)).toBe(palette().other)
  })

  it('has a distinct step for dark mode rather than reusing the light one', () => {
    for (const sport of PALETTE_SLOTS) {
      expect(sportColor(sport, true)).not.toBe(sportColor(sport, false))
    }
  })
})

describe('seriesColors', () => {
  it('hands out the slots in order, so a chart never cycles hues', () => {
    expect(seriesColors(3)).toEqual([palette().cycling, palette().running, palette().hiking])
  })

  it('gives a shorter chart the same colours as a longer one', () => {
    // Colour follows the entity: losing a series must not repaint the ones
    // that stayed, so the shorter list is a prefix of the longer.
    const three = seriesColors(3)
    expect(seriesColors(2)).toEqual(three.slice(0, 2))
  })

  it('stops at the four validated slots rather than inventing a fifth', () => {
    expect(seriesColors(9)).toHaveLength(PALETTE_SLOTS.length)
  })

  it('steps dark mode separately', () => {
    expect(seriesColors(3, true)).not.toEqual(seriesColors(3, false))
  })
})
