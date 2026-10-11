import '@testing-library/jest-dom/vitest'
import { cleanup } from '@testing-library/react'
import { afterEach, beforeEach, vi } from 'vitest'
import { setSports } from '../src/sports'
import sports from './sports.json'

/**
 * Fail any test that makes React complain.
 *
 * eslint-plugin-react is absent from the lint config because its latest
 * release does not support ESLint 10, and the rule it is most missed for is
 * react/jsx-key. React logs a console error for a missing key, an invalid prop
 * or a bad nesting, so turning those logs into failures covers the same ground
 * at the point where it actually matters.
 */
let logged = []

beforeEach(() => {
  logged = []
  vi.spyOn(console, 'error').mockImplementation((...args) => {
    logged.push(args.map(String).join(' '))
  })
})

afterEach(() => {
  cleanup()
  const captured = [...logged]
  vi.restoreAllMocks()
  if (captured.length) {
    throw new Error(`React logged ${captured.length} error(s):\n${captured.join('\n')}`)
  }
})

/**
 * The sport catalogue the app loads at startup, from a copy of what the API
 * serves. backend/tests/test_sports.py fails if the copy drifts from the real
 * thing, so it cannot quietly become a second definition.
 */
beforeEach(() => setSports(sports))
