import { useRef, useState } from 'react'
import { errorMessage, fetchArchiveImport, uploadArchive, uploadWorkout } from '../api/client'

const ACTIVITY_SUFFIXES = ['.tcx', '.gpx', '.fit']
const ARCHIVE_SUFFIXES = ['.zip']
const ALL_SUFFIXES = [...ACTIVITY_SUFFIXES, ...ARCHIVE_SUFFIXES]
const ACCEPT = ALL_SUFFIXES.join(',')

/**
 * Deliberately generous: this is only here to stop a pathological file being
 * uploaded for no reason. The server holds the real limits, and rejecting
 * something it would have accepted is worse than a wasted request — so this
 * ceiling sits well above any plausible configuration.
 */
const ABSURD_SIZE = 500 * 1024 * 1024

/**
 * How many polls in a row may fail before giving up on following an import.
 * One dropped request on a flaky connection is no reason to stop watching.
 */
const MAX_POLL_MISSES = 5

const wait = (ms) => new Promise((resolve) => setTimeout(resolve, ms))

function suffixOf(name) {
  const lowered = name.toLowerCase()
  return ALL_SUFFIXES.find((s) => lowered.endsWith(s)) ?? null
}

/** Why this file cannot be sent, or null if it can. */
function precheck(file) {
  if (!suffixOf(file.name)) return `not one of ${ALL_SUFFIXES.join(', ')}`
  if (file.size === 0) return 'the file is empty'
  if (file.size > ABSURD_SIZE) return 'far too large to upload'
  return null
}

/**
 * Uploads activity files, or a whole export archive.
 *
 * Results appear as each file finishes rather than at the end of the batch: a
 * Strava export is hundreds of files, and minutes of silence with no counter
 * is indistinguishable from a hang.
 *
 * An archive is imported by the server after the upload is answered — a full
 * export takes minutes, past what any proxy holds a request open for — so it is
 * followed by polling, with its own "n of m files" counter.
 *
 * Sending is sequential, and that is load-bearing rather than merely simple.
 * The server's near-duplicate check reads before it writes, so two files
 * describing the same session could both pass it if they went up at once — and
 * the unique constraint would not catch them either, since their bytes differ.
 * That includes waiting for an archive's import to end before the next file.
 */
export default function UploadForm({ userId, onUploaded, pollMs = 1000 }) {
  const fileInput = useRef(null)
  const folderInput = useRef(null)
  const [rows, setRows] = useState([])
  const [tally, setTally] = useState(null)
  const [progress, setProgress] = useState(null)
  const [importing, setImporting] = useState(null)
  const [dragging, setDragging] = useState(false)

  function summarise(archive, filename) {
    const parts = []
    if (archive.stored) parts.push(`${archive.stored} added`)
    if (archive.duplicates) parts.push(`${archive.duplicates} already here`)
    if (archive.skipped) parts.push(`${archive.skipped} skipped`)
    if (archive.failed) parts.push(`${archive.failed} failed`)

    // Only the members that need attention: nobody reads three hundred lines
    // saying "added".
    const problems = archive.members
      .filter((member) => member.outcome === 'failed')
      .map((member) => ({
        name: `${filename} → ${member.filename}`,
        state: 'rejected',
        detail: member.detail,
      }))

    // An import that stopped part-way still stored what it got to, and says so.
    const ended = archive.status === 'done'
    const counted = parts.join(', ') || (ended ? 'nothing to import' : 'nothing imported')

    return {
      rows: [
        {
          name: filename,
          state: !ended ? 'rejected' : archive.stored ? 'stored' : 'duplicate',
          detail: ended ? counted : `${archive.error ?? 'the import stopped'} (${counted})`,
        },
        ...problems,
      ],
      // The real numbers, not the row count: one row can stand for hundreds of
      // activities, and a summary that said "1 added" for a 300-file import
      // would be worse than no summary.
      tally: {
        stored: archive.stored,
        duplicate: archive.duplicates,
        skipped: archive.skipped,
        rejected: archive.failed + (ended ? 0 : 1),
      },
    }
  }

  /** Poll an import until it is no longer running, showing how far it has got. */
  async function follow(job, filename) {
    let misses = 0
    try {
      while (job.status === 'running') {
        setImporting({ name: filename, processed: job.processed, total: job.total })
        await wait(pollMs)
        try {
          job = await fetchArchiveImport(userId, job.id)
          misses = 0
        } catch (caught) {
          misses += 1
          if (misses >= MAX_POLL_MISSES) {
            // The import itself is most likely fine and still going: it is
            // only the watching that failed.
            throw new Error(
              `Lost track of the import (${errorMessage(caught, 'no answer')}). ` +
                'It may still be running: reload in a while to see what arrived.',
              { cause: caught },
            )
          }
        }
      }
      return job
    } finally {
      setImporting(null)
    }
  }

  async function sendOne(file) {
    const isArchive = ARCHIVE_SUFFIXES.includes(suffixOf(file.name))
    try {
      if (isArchive) {
        const job = await uploadArchive(userId, file)
        return summarise(await follow(job, file.name), file.name)
      }
      const workout = await uploadWorkout(userId, file)
      return {
        rows: [{ name: file.name, state: 'stored', detail: workout.name }],
        tally: { stored: 1 },
      }
    } catch (caught) {
      const status = caught?.response?.status
      // A 409 on one file means it is already stored. On an archive it means
      // another import is still running, which is no reason to look settled.
      const state = status === 409 && !isArchive ? 'duplicate' : 'rejected'
      return {
        rows: [
          { name: file.name, state, detail: errorMessage(caught, 'Upload failed') },
        ],
        tally: { [state]: 1 },
      }
    }
  }

  async function send(files) {
    if (!files.length) return

    const accepted = []
    const refused = []
    for (const file of files) {
      const reason = precheck(file)
      if (reason) refused.push({ name: file.name, state: 'rejected', detail: reason })
      else accepted.push(file)
    }

    // Show what was refused before spending a single request on the rest.
    setRows(refused)
    setTally({ rejected: refused.length })
    setProgress({ done: 0, total: accepted.length })

    let added = 0
    for (const [index, file] of accepted.entries()) {
      const { rows: newRows, tally: counted } = await sendOne(file)
      added += counted.stored ?? 0
      setRows((previous) => [...previous, ...newRows])
      setTally((previous) => {
        const merged = { ...previous }
        for (const [key, value] of Object.entries(counted)) {
          merged[key] = (merged[key] ?? 0) + (value ?? 0)
        }
        return merged
      })
      setProgress({ done: index + 1, total: accepted.length })
    }

    setProgress(null)
    if (added) onUploaded()
    for (const input of [fileInput, folderInput]) {
      if (input.current) input.current.value = ''
    }
  }

  function onDrop(event) {
    event.preventDefault()
    setDragging(false)
    send(Array.from(event.dataTransfer?.files ?? []))
  }

  const busy = progress !== null

  return (
    <section className="panel p-4" aria-labelledby="upload-heading">
      <h2 id="upload-heading" className="text-sm font-semibold">
        Add activities
      </h2>
      <p className="mt-1 text-xs muted">
        FIT or TCX from Garmin, GPX from Strava or Komoot, or the whole export as a .zip.
        Files already stored are skipped.
      </p>

      <div
        onDragOver={(event) => {
          event.preventDefault()
          setDragging(true)
        }}
        onDragLeave={() => setDragging(false)}
        onDrop={onDrop}
        data-testid="dropzone"
        className={`mt-3 rounded-md border-2 border-dashed p-4 text-center transition-colors ${
          dragging ? 'border-sky-600 bg-sky-50 dark:bg-sky-950' : 'border-[var(--border)]'
        }`}
      >
        <p className="text-sm muted">Drop files or a .zip here</p>

        <div className="mt-3 flex flex-wrap justify-center gap-2">
          <label className="cursor-pointer rounded-md bg-sky-700 px-3 py-2 text-sm font-medium text-white hover:bg-sky-800">
            Choose files
            <input
              ref={fileInput}
              type="file"
              multiple
              accept={ACCEPT}
              aria-label="Activity files"
              disabled={busy}
              onChange={(event) => send(Array.from(event.target.files ?? []))}
              className="hidden"
            />
          </label>

          <label className="cursor-pointer rounded-md border border-[var(--border)] px-3 py-2 text-sm font-medium hover:bg-[var(--surface-sunken)]">
            Choose a folder
            <input
              ref={folderInput}
              type="file"
              multiple
              aria-label="Activity folder"
              disabled={busy}
              // Non-standard but universally supported, and the only way to
              // pick an unzipped export without selecting every file by hand.
              {...{ webkitdirectory: '', directory: '' }}
              onChange={(event) => send(Array.from(event.target.files ?? []))}
              className="hidden"
            />
          </label>
        </div>
      </div>

      {busy && (
        <p className="mt-3 text-sm muted" role="status">
          {importing
            ? `Importing ${importing.name}: ${importing.processed} of ${importing.total} files…`
            : `Uploading ${progress.done} of ${progress.total}…`}
        </p>
      )}

      {!busy && tally && (
        <p className="mt-3 text-sm font-medium" role="status">
          {[
            tally.stored && `${tally.stored} added`,
            tally.duplicate && `${tally.duplicate} already here`,
            tally.skipped && `${tally.skipped} skipped`,
            tally.rejected && `${tally.rejected} rejected`,
          ]
            .filter(Boolean)
            .join(' · ') || 'nothing to import'}
        </p>
      )}

      {rows.length > 0 && (
        <ul className="mt-2 max-h-64 space-y-1 overflow-y-auto text-sm" aria-live="polite">
          {rows.map((row, index) => (
            <li key={`${row.name}-${index}`} className="flex gap-2">
              <span
                className={
                  row.state === 'stored'
                    ? 'text-green-700 dark:text-green-400'
                    : row.state === 'duplicate'
                      ? 'muted'
                      : 'text-red-700 dark:text-red-400'
                }
              >
                {row.state === 'stored'
                  ? 'Added'
                  : row.state === 'duplicate'
                    ? 'Already here'
                    : 'Rejected'}
              </span>
              <span className="truncate">{row.name}</span>
              {row.detail && <span className="muted truncate">— {row.detail}</span>}
            </li>
          ))}
        </ul>
      )}
    </section>
  )
}
