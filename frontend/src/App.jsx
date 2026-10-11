import { useEffect, useState } from 'react'
import { errorMessage, fetchProfile, fetchSports } from './api/client'
import Dashboard from './components/Dashboard'
import FirstRunScreen from './components/FirstRunScreen'
import Footer from './components/Footer'
import { setSports } from './sports'

/**
 * Decides between the first-run screen and the dashboard.
 *
 * A 404 from /users/me is not an error: it means nobody has introduced
 * themselves yet, which is exactly what the first-run screen is for.
 *
 * The sport catalogue is loaded alongside, and before anything renders: every
 * label, pace and colour on the dashboard reads from it synchronously.
 */
export default function App() {
  const [state, setState] = useState({ status: 'loading' })

  useEffect(() => {
    let cancelled = false
    Promise.all([fetchProfile(), fetchSports()])
      .then(([profile, sports]) => {
        if (cancelled) return
        setSports(sports)
        setState({ status: 'ready', profile })
      })
      .catch((caught) => {
        if (!cancelled) setState({ status: 'error', message: errorMessage(caught) })
      })
    return () => {
      cancelled = true
    }
  }, [])

  // One shell around every state, so the footer is on all of them — and a
  // column with a growing body rather than a full-height view plus a footer
  // after it, which would push the footer below the fold on a short screen.
  //
  // `*:w-full` is load-bearing, in the same family as the `*:min-w-0` in the
  // dashboard's grids. Whatever this box holds becomes a flex item, and a flex
  // item's cross size is fit-content rather than "fill the parent" — so the
  // activity table dragged the dashboard out to 339px inside a 320px column,
  // and the document with it. An explicit width takes that away.
  return (
    <div className="flex min-h-screen flex-col">
      <div className="flex flex-1 flex-col *:w-full">{view(state, setState)}</div>
      <Footer />
    </div>
  )
}

function view(state, setState) {
  if (state.status === 'loading') {
    return (
      <p className="p-8 text-sm text-slate-600 dark:text-slate-400" role="status">
        Loading…
      </p>
    )
  }

  if (state.status === 'error') {
    return (
      <div className="mx-auto max-w-md p-8">
        <h1 className="text-lg font-semibold">Cannot reach the API</h1>
        <p role="alert" className="mt-2 text-sm text-red-700 dark:text-red-400">
          {state.message}
        </p>
      </div>
    )
  }

  if (!state.profile) {
    return <FirstRunScreen onCreated={(profile) => setState({ status: 'ready', profile })} />
  }

  return <Dashboard profile={state.profile} />
}
