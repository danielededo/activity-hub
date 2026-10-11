import { act, fireEvent, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import UploadForm from '../src/components/UploadForm'
import * as api from '../src/api/client'

vi.mock('../src/api/client', () => ({
  uploadWorkout: vi.fn(),
  uploadArchive: vi.fn(),
  fetchArchiveImport: vi.fn(),
  errorMessage: (error, fallback) => error?.response?.data?.detail ?? error?.message ?? fallback,
}))

const file = (name) => new File(['<gpx/>'], name, { type: 'application/xml' })
const zip = (name = 'export.zip') => new File(['PK\x03\x04'], name, { type: 'application/zip' })
const empty = (name) => new File([], name, { type: 'application/xml' })

/** An archive import that has finished; `running()` is one that has not. */
function archiveResult(overrides = {}) {
  return {
    id: 7,
    status: 'done',
    total: 0,
    processed: 0,
    stored: 0,
    duplicates: 0,
    skipped: 0,
    failed: 0,
    members: [],
    truncated: false,
    error: null,
    ...overrides,
  }
}

const running = (overrides = {}) => archiveResult({ status: 'running', ...overrides })

function rejectWith(status, detail) {
  return Object.assign(new Error(detail), { response: { status, data: { detail } } })
}

describe('UploadForm', () => {
  beforeEach(() => vi.clearAllMocks())

  it('reports a stored file and refreshes the dashboard', async () => {
    api.uploadWorkout.mockResolvedValue({ id: 1, name: 'Morning ride' })
    const onUploaded = vi.fn()
    render(<UploadForm userId={1} onUploaded={onUploaded} />)

    await userEvent.upload(screen.getByLabelText(/activity files/i), file('ride.gpx'))

    expect(await screen.findByText('Added')).toBeVisible()
    expect(onUploaded).toHaveBeenCalledOnce()
  })

  it('treats an already-stored file as normal, not as a failure', async () => {
    // Re-uploading a folder where half is present is the ordinary case.
    api.uploadWorkout.mockRejectedValue(rejectWith(409, 'Already stored as workout 3'))
    const onUploaded = vi.fn()
    render(<UploadForm userId={1} onUploaded={onUploaded} />)

    await userEvent.upload(screen.getByLabelText(/activity files/i), file('ride.gpx'))

    expect(await screen.findByText('Already here')).toBeVisible()
    expect(onUploaded).not.toHaveBeenCalled()
  })

  it('shows the reason a file was rejected', async () => {
    api.uploadWorkout.mockRejectedValue(rejectWith(422, 'Malformed XML: mismatched tag'))
    render(<UploadForm userId={1} onUploaded={vi.fn()} />)

    await userEvent.upload(screen.getByLabelText(/activity files/i), file('broken.gpx'))

    expect(await screen.findByText('Rejected')).toBeVisible()
    expect(screen.getByText(/mismatched tag/i)).toBeInTheDocument()
  })

  it('reports each file in a batch separately', async () => {
    api.uploadWorkout
      .mockResolvedValueOnce({ id: 1, name: 'One' })
      .mockRejectedValueOnce(rejectWith(409, 'Already stored as workout 1'))
    const onUploaded = vi.fn()
    render(<UploadForm userId={1} onUploaded={onUploaded} />)

    await userEvent.upload(screen.getByLabelText(/activity files/i), [
      file('a.gpx'),
      file('b.gpx'),
    ])

    expect(await screen.findByText('Added')).toBeVisible()
    expect(screen.getByText('Already here')).toBeVisible()
    // One of the two landed, so the dashboard still needs refreshing.
    await waitFor(() => expect(onUploaded).toHaveBeenCalledOnce())
  })
})


// -- archives ------------------------------------------------------------

describe('UploadForm with an archive', () => {
  beforeEach(() => vi.clearAllMocks())

  it('sends a zip to the archive endpoint, not the single-file one', async () => {
    api.uploadArchive.mockResolvedValue(archiveResult({ stored: 22, skipped: 2 }))
    render(<UploadForm userId={1} onUploaded={vi.fn()} />)

    await userEvent.upload(screen.getByLabelText(/activity files/i), zip())

    expect(api.uploadArchive).toHaveBeenCalledOnce()
    expect(api.uploadWorkout).not.toHaveBeenCalled()
  })

  it('summarises the archive instead of listing every file in it', async () => {
    // Nobody reads three hundred lines saying "added".
    api.uploadArchive.mockResolvedValue(
      archiveResult({
        stored: 22,
        duplicates: 1,
        skipped: 2,
        members: Array.from({ length: 25 }, (_, i) => ({
          filename: `a-${i}.gpx`,
          outcome: 'stored',
          workout_id: i,
        })),
      }),
    )
    render(<UploadForm userId={1} onUploaded={vi.fn()} />)

    await userEvent.upload(screen.getByLabelText(/activity files/i), zip())

    expect(await screen.findByText(/22 added, 1 already here, 2 skipped/)).toBeVisible()
    expect(screen.queryByText('a-0.gpx')).not.toBeInTheDocument()
  })

  it('does list the members that failed, since those need attention', async () => {
    api.uploadArchive.mockResolvedValue(
      archiveResult({
        stored: 2,
        failed: 1,
        members: [
          { filename: 'good.gpx', outcome: 'stored', workout_id: 1 },
          { filename: 'broken.gpx', outcome: 'failed', detail: 'Malformed XML' },
        ],
      }),
    )
    render(<UploadForm userId={1} onUploaded={vi.fn()} />)

    await userEvent.upload(screen.getByLabelText(/activity files/i), zip())

    expect(await screen.findByText(/export\.zip → broken\.gpx/)).toBeVisible()
    expect(screen.getByText(/Malformed XML/)).toBeVisible()
  })

  it('counts the activities in an archive, not the rows shown for it', async () => {
    // One row can stand for hundreds of activities. A summary reading
    // "1 added" after importing an export of 22 is worse than none.
    api.uploadArchive.mockResolvedValue(
      archiveResult({ stored: 22, skipped: 1, failed: 1, members: [] }),
    )
    render(<UploadForm userId={1} onUploaded={vi.fn()} />)

    await userEvent.upload(screen.getByLabelText(/activity files/i), zip())

    expect(await screen.findByRole('status')).toHaveTextContent(
      '22 added · 1 skipped · 1 rejected',
    )
  })

  it('refreshes the dashboard when an archive stored anything', async () => {
    api.uploadArchive.mockResolvedValue(archiveResult({ stored: 5 }))
    const onUploaded = vi.fn()
    render(<UploadForm userId={1} onUploaded={onUploaded} />)

    await userEvent.upload(screen.getByLabelText(/activity files/i), zip())

    await waitFor(() => expect(onUploaded).toHaveBeenCalledOnce())
  })

  it('does not refresh when an archive imported nothing', async () => {
    api.uploadArchive.mockResolvedValue(archiveResult({ duplicates: 3 }))
    const onUploaded = vi.fn()
    render(<UploadForm userId={1} onUploaded={onUploaded} />)

    await userEvent.upload(screen.getByLabelText(/activity files/i), zip())

    const summary = await screen.findByRole('status')
    expect(summary).toHaveTextContent('3 already here')
    expect(onUploaded).not.toHaveBeenCalled()
  })
})

// -- following an import -------------------------------------------------

describe('UploadForm following an archive import', () => {
  beforeEach(() => vi.clearAllMocks())

  it('polls a running import until it is done, then summarises it', async () => {
    api.uploadArchive.mockResolvedValue(running({ total: 150 }))
    api.fetchArchiveImport
      .mockResolvedValueOnce(running({ total: 150, processed: 60, stored: 60 }))
      .mockResolvedValueOnce(archiveResult({ total: 150, processed: 150, stored: 150 }))
    const onUploaded = vi.fn()
    render(<UploadForm userId={1} onUploaded={onUploaded} pollMs={0} />)

    await userEvent.upload(screen.getByLabelText(/activity files/i), zip())

    await waitFor(() => expect(screen.getByRole('status')).toHaveTextContent('150 added'))
    expect(api.fetchArchiveImport).toHaveBeenCalledTimes(2)
    expect(api.fetchArchiveImport).toHaveBeenCalledWith(1, 7)
    expect(onUploaded).toHaveBeenCalledOnce()
  })

  it('shows how far a running import has got', async () => {
    api.uploadArchive.mockResolvedValue(running({ total: 150 }))
    // Never settles: the import is still going when the test looks.
    api.fetchArchiveImport.mockReturnValue(new Promise(() => {}))
    render(<UploadForm userId={1} onUploaded={vi.fn()} pollMs={0} />)

    await userEvent.upload(screen.getByLabelText(/activity files/i), zip('garmin.zip'))

    expect(await screen.findByRole('status')).toHaveTextContent(
      'Importing garmin.zip: 0 of 150 files…',
    )
  })

  it('reports an import that stopped part-way, with what it did store', async () => {
    api.uploadArchive.mockResolvedValue(running({ total: 150 }))
    api.fetchArchiveImport.mockResolvedValue(
      archiveResult({
        status: 'interrupted',
        total: 150,
        processed: 40,
        stored: 40,
        error: 'The import stopped before it finished',
      }),
    )
    const onUploaded = vi.fn()
    render(<UploadForm userId={1} onUploaded={onUploaded} pollMs={0} />)

    await userEvent.upload(screen.getByLabelText(/activity files/i), zip())

    expect(await screen.findByText('Rejected')).toBeVisible()
    expect(screen.getByText(/stopped before it finished \(40 added\)/)).toBeVisible()
    // Forty activities did arrive, so the dashboard has something new to show.
    await waitFor(() => expect(onUploaded).toHaveBeenCalledOnce())
  })

  it('keeps following through a dropped poll', async () => {
    api.uploadArchive.mockResolvedValue(running({ total: 3 }))
    api.fetchArchiveImport
      .mockRejectedValueOnce(new Error('Network Error'))
      .mockResolvedValueOnce(archiveResult({ total: 3, processed: 3, stored: 3 }))
    render(<UploadForm userId={1} onUploaded={vi.fn()} pollMs={0} />)

    await userEvent.upload(screen.getByLabelText(/activity files/i), zip())

    await waitFor(() => expect(screen.getByRole('status')).toHaveTextContent('3 added'))
  })

  it('says the import may still be running when polling keeps failing', async () => {
    api.uploadArchive.mockResolvedValue(running({ total: 3 }))
    api.fetchArchiveImport.mockRejectedValue(new Error('Network Error'))
    render(<UploadForm userId={1} onUploaded={vi.fn()} pollMs={0} />)

    await userEvent.upload(screen.getByLabelText(/activity files/i), zip())

    expect(await screen.findByText(/may still be running/)).toBeVisible()
    expect(api.fetchArchiveImport).toHaveBeenCalledTimes(5)
  })

  it('treats a second archive refused while one imports as rejected, not as here', async () => {
    api.uploadArchive.mockRejectedValue(rejectWith(409, 'Archive import 3 is still running'))
    render(<UploadForm userId={1} onUploaded={vi.fn()} />)

    await userEvent.upload(screen.getByLabelText(/activity files/i), zip())

    expect(await screen.findByText('Rejected')).toBeVisible()
    expect(screen.getByText(/still running/)).toBeVisible()
  })
})

// -- what never reaches the network -------------------------------------

describe('UploadForm pre-checks', () => {
  beforeEach(() => vi.clearAllMocks())

  it('refuses a file that is not an activity or an archive', async () => {
    // Dropped, not picked: the input's `accept` already filters the picker, so
    // drag and drop is the path where this check actually earns its place.
    render(<UploadForm userId={1} onUploaded={vi.fn()} />)

    fireEvent.drop(screen.getByTestId('dropzone'), {
      dataTransfer: { files: [file('notes.pdf')] },
    })

    expect(await screen.findByText(/not one of \.tcx, \.gpx, \.fit, \.zip/)).toBeVisible()
    expect(api.uploadWorkout).not.toHaveBeenCalled()
  })

  it('refuses an empty file without asking the server', async () => {
    render(<UploadForm userId={1} onUploaded={vi.fn()} />)

    await userEvent.upload(screen.getByLabelText(/activity files/i), empty('ride.gpx'))

    expect(await screen.findByText(/the file is empty/)).toBeVisible()
    expect(api.uploadWorkout).not.toHaveBeenCalled()
  })

  it('lets the picker filter by extension, so that path needs no check', () => {
    // Documenting the division of labour: `accept` handles the picker, the
    // precheck handles everything dropped on the zone.
    render(<UploadForm userId={1} onUploaded={vi.fn()} />)

    expect(screen.getByLabelText(/activity files/i)).toHaveAttribute(
      'accept',
      '.tcx,.gpx,.fit,.zip',
    )
  })

  it('still uploads the good files in a mixed drop', async () => {
    api.uploadWorkout.mockResolvedValue({ id: 1, name: 'Ride' })
    render(<UploadForm userId={1} onUploaded={vi.fn()} />)

    fireEvent.drop(screen.getByTestId('dropzone'), {
      dataTransfer: { files: [file('notes.pdf'), file('ride.gpx')] },
    })

    expect(await screen.findByText('Added')).toBeVisible()
    expect(screen.getByText(/not one of \.tcx/)).toBeVisible()
    expect(api.uploadWorkout).toHaveBeenCalledOnce()
  })
})

// -- progress ------------------------------------------------------------

describe('UploadForm progress', () => {
  beforeEach(() => vi.clearAllMocks())

  it('shows each result as it lands, not at the end of the batch', async () => {
    // The whole point: a few hundred files used to mean minutes of silence,
    // which is indistinguishable from a hang.
    let releaseSecond
    api.uploadWorkout
      .mockResolvedValueOnce({ id: 1, name: 'First' })
      .mockImplementationOnce(() => new Promise((resolve) => { releaseSecond = resolve }))
    render(<UploadForm userId={1} onUploaded={vi.fn()} />)

    await userEvent.upload(screen.getByLabelText(/activity files/i), [
      file('a.gpx'),
      file('b.gpx'),
    ])

    // First one visible while the second is still in flight.
    expect(await screen.findByText('a.gpx')).toBeVisible()
    expect(screen.getByRole('status')).toHaveTextContent('Uploading 1 of 2')

    await act(async () => releaseSecond({ id: 2, name: 'Second' }))
    expect(await screen.findByText('b.gpx')).toBeVisible()
  })

  it('counts the batch rather than just saying "uploading"', async () => {
    const pending = []
    api.uploadWorkout.mockImplementation(
      () => new Promise((resolve) => pending.push(resolve)),
    )
    render(<UploadForm userId={1} onUploaded={vi.fn()} />)

    await userEvent.upload(screen.getByLabelText(/activity files/i), [
      file('a.gpx'),
      file('b.gpx'),
      file('c.gpx'),
    ])

    expect(await screen.findByText(/Uploading 0 of 3/)).toBeVisible()

    // Drain inside act, or React logs an update after the test has finished.
    await act(async () => {
      pending.forEach((resolve, index) => resolve({ id: index, name: 'One' }))
    })
  })

  it('ends with a summary of the batch', async () => {
    api.uploadWorkout
      .mockResolvedValueOnce({ id: 1, name: 'One' })
      .mockRejectedValueOnce(rejectWith(409, 'Already stored as workout 1'))
    render(<UploadForm userId={1} onUploaded={vi.fn()} />)

    await userEvent.upload(screen.getByLabelText(/activity files/i), [
      file('a.gpx'),
      file('b.gpx'),
    ])

    expect(await screen.findByText('1 added · 1 already here')).toBeVisible()
  })
})

// -- other ways in ------------------------------------------------------

describe('UploadForm entry points', () => {
  beforeEach(() => vi.clearAllMocks())

  it('accepts dropped files', async () => {
    api.uploadWorkout.mockResolvedValue({ id: 1, name: 'Ride' })
    render(<UploadForm userId={1} onUploaded={vi.fn()} />)

    const dropped = file('ride.gpx')
    fireEvent.drop(screen.getByTestId('dropzone'), { dataTransfer: { files: [dropped] } })

    expect(await screen.findByText('Added')).toBeVisible()
    expect(api.uploadWorkout).toHaveBeenCalledWith(1, dropped)
  })

  it('offers a folder picker, for an export that was already unzipped', async () => {
    api.uploadWorkout.mockResolvedValue({ id: 1, name: 'Ride' })
    render(<UploadForm userId={1} onUploaded={vi.fn()} />)

    await userEvent.upload(screen.getByLabelText(/activity folder/i), file('ride.gpx'))

    expect(await screen.findByText('Added')).toBeVisible()
  })
})
