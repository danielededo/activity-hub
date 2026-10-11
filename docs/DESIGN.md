# Why it works the way it does

A record of the decisions behind Activity Hub, so a future change knows what it
would be undoing. Most entries exist because the obvious alternative was tried,
or because looking at the rendered page showed the obvious alternative was
wrong.

The README is the front door: what the app is, how to run it, what the API
offers. This is the long half.

- [Sports](#sports)
- [Reading the files](#reading-the-files)
- [The numbers](#the-numbers)
- [The charts](#the-charts)
- [The route](#the-route)
- [Heart-rate zones and load](#heart-rate-zones-and-load)
- [Fitness, fatigue and form](#fitness-fatigue-and-form)
- [Personal bests](#personal-bests)
- [Comparing two activities](#comparing-two-activities)
- [Narrow screens](#narrow-screens)
- [Filtering, deleting, exporting](#filtering-deleting-exporting)

## Sports

**A sport is defined in one place.** `backend/app/services/sports.py` holds,
for each sport, everything that differs between them: its label, whether it
reads as pace or speed, its cadence unit, its colour, and what each file format
calls it. Before it, those facts lived in a table per parser and in four places
in the frontend, and adding a sport meant finding all seven. The parsers read
the catalogue directly; the dashboard loads it from `GET /api/sports` before it
renders anything.

**File aliases are per format.** Strava writes `9` for a run in GPX; nothing
says a `9` means anything in TCX. A shared alias list would make one format's
quirk another's rule.

**An unknown sport is kept, not folded into "other".** A FIT file that says
`rowing` is stored as `rowing` and shown by speed in the "other" colour until it
has an entry — the name is more use than a bucket, and adding the entry later
needs no backfill, because the stored key was right all along.

**Colour is a slot, not a hue.** The palette has four validated colours and a
fifth picked by eye can be invisible to a colourblind reader, so a sport names
one of the four slots. Most take "other"; the distinction a colour cannot carry
is carried by the label beside it.

**The frontend tests read a copy, and a backend test guards it.** They run
without a server, so they need the catalogue as a file; the backend suite fails
the moment that file and the API disagree, so it cannot quietly become a second
definition.

## Reading the files

**The file's own totals win.** Garmin measures distance with a wheel or a
footpod, which beats integrating GPS positions. Only the gaps are derived —
distance by the haversine formula, discarding implausible jumps from dropped
signal, and elevation gain and loss ignoring changes under 1 m as jitter.

**Element lookups are namespace-agnostic.** Vendors vary the namespace and
nothing else; matching on the local name means no per-vendor special cases.

**FIT is not an optional third format.** It is what a Garmin watch records, and
a bulk export keeps every activity in the format it was uploaded in — so for
anyone arriving with their whole Garmin history, FIT is the *only* format in the
box. While `.fit` was missing from the archive's suffix list an eight-hundred
ride export reported `stored=0, skipped=800` and looked like it had worked,
which is the worst way for an importer to fail.

**Decoded with `fitdecode`, not Garmin's own SDK.** The official SDK is the
better-maintained library, and it ships under the FIT Protocol License rather
than an open-source one, which is not a licence this project can take a
dependency on. `fitdecode` is MIT and reads the message types a training log
needs.

**Positions are converted by hand rather than by the library's unit
processor.** `StandardUnitsDataProcessor` does convert semicircles to degrees —
and also converts session distance from metres to kilometres, which would store
every activity a thousand times shorter than it was, with nothing downstream
noticing. Converting one field by hand is cheaper than auditing every field a
processor touches, so the default processor is used and a semicircle is
multiplied by `180 / 2^31` here.

**`total_timer_time`, not `total_elapsed_time`.** The timer stops when you do,
so it is the moving time the rest of the app means; elapsed time includes the
twenty minutes at the café.

**A record with no position is kept.** An indoor ride on a trainer has heart
rate and cadence and no GPS at all, and dropping those samples would throw away
the only traces it has.

**FIT is recognised by its signature as well as its name.** The other two
parsers decide by root element, which cannot work on a binary file; bytes 8–12
of a FIT header are `.FIT`, and that is what identifies an archive member named
by activity id with no extension at all.

**Timestamps are stored as UTC, and the stated offset is kept beside them.**
TCX and GPX normally write `Z`, which fixes the instant but says nothing about
the local hour. FIT is the one format that always says it, by writing each
instant twice — once as UTC, once as local wall clock — so the difference is the
offset. Any offset a file states goes in `utc_offset_minutes`, and
`DISPLAY_TIMEZONE` is the fallback. Weekly totals bucket by local week: a 00:30
Monday ride in Rome belongs to that Monday, not to the Sunday it falls on in UTC.

**`raw_data` holds file-level metadata only** — creator, author, lap summaries,
counts. The samples live in `track_points`, so nothing is stored twice.

**An archive from a user is hostile input.** Both the declared uncompressed
total and each member are capped, and every read is bounded, so a header that
lies cannot turn into memory use either; the entry count is capped against
member floods; nested archives are refused rather than recursed into. Path
traversal is absent by construction — members are read into memory, never
extracted to disk, so there is no path to traverse.

**A real export is full of CSVs and images, so those are *skipped*, not
errors**, and one corrupt file does not stop the other three hundred.

**Members are processed one at a time**, which is load-bearing rather than
merely simple: the near-duplicate check reads before it writes, so two files
describing the same session could both pass it if they were handled at once —
and the unique constraint would not catch them either, since their bytes differ.

**An archive is imported after the upload is answered, not during it.** One
activity takes a second or more to parse and store, so a full export is minutes
of work. Done inside the request, 150 FIT files outlasted nginx's two minutes:
the browser was shown a 504 at the halfway mark, while the import carried on and
finished two minutes later with nobody watching. Now the upload checks what can
refuse the archive as a whole — size, a readable zip, member count, the zip-bomb
total, an import already running — answers `202`, and the work continues behind
it, writing progress to an `archive_imports` row the dashboard polls.

**One import at a time per user**, for the same reason as one member at a time:
two imports racing could each store the same session from a different file.

**A running import that goes quiet is reported as interrupted.** The worker
writes a heartbeat after every file, and a worker that dies with the process
cannot say it has stopped — without this its import would read `running` forever
and refuse the next one. A file takes a second or two, so
`ARCHIVE_IMPORT_STALE_SECONDS` (five minutes) is far from any real pause, and
sending the archive again is cheap: files already stored are recognised by their
hash before any parsing.

**Duplicates are two questions, answered separately.** `(user_id, file_hash)` is
unique, so the same bytes cannot be stored twice whatever the file is named —
exact, and enforced by the database. That misses the same ride exported from
Garmin as TCX and from Strava as GPX: different bytes, different `source`, one
session. Those are recognised by what they describe — same sport, starting
within `DUPLICATE_WINDOW_SECONDS` — which no constraint can express, so the
check lives in the service layer. A brick session still works: a ride and a run
at the same time are different sports.

**The exact question is asked before the file is parsed.** Parsing is most of
what a file costs, and an export sent a second time is almost entirely files
already stored — so hashing first took re-sending a 150-activity export from
130 s to under a second.

**A backfill that can tell "not computed" from "computed, nothing there" only
visits an activity once.** The heart-rate histogram records an empty value for an
activity that carried no heart rate, so a strapless one is not rescanned on every
run — unlike the personal-bests backfill, which cannot distinguish the two and so
re-reads every activity too short to hold a record. The distinction is
load-bearing beyond the backfill: SQLAlchemy stores Python `None` in a JSON
column as the JSON *value* `null` unless told otherwise, which made `IS NULL`
match nothing and silently disabled the whole scheme until a database-level test
caught it. Anything asking "did this activity have a heart rate" must treat both
the empty value and NULL as no — a later count of load-free activities got that
wrong and reported zero on a library with six.

**Activity files cannot supply your name.** GPX 1.1 has a slot for it
(`metadata/author/name`) and TCX has none — its `Author` is the application and
its `Creator` is the device — and in practice the big exporters leave it empty
anyway, which is the right call for personal data. So the dashboard asks once.

## The numbers

**Metric only, no unit toggle.** Runners get minutes per kilometre, cyclists get
km/h.

**Times are the activity's own local time**, from the offset its file stated, in
24-hour form. Falling back to the viewer's locale for the no-offset case put
"06:45 PM" and "08:45" in the same column, which reads as two different kinds of
number rather than as two activities.

**Cadence is reported as recorded, in the sport's own unit.** Cycling is crank
revolutions per minute. On foot, TCX `RunCadence` and GPX `cad` are written per
leg, so the figure is strides per minute — roughly half the steps-per-minute a
watch shows. It is not doubled to match: nothing in either format says which
convention a file used, and an exporter that already counts both feet would then
read twice as fast as the run was.

## The charts

**Weekly distance is bars, not a line.** The weeks are discrete buckets; a line
between them would imply a continuous quantity nobody measured, and a quiet week
is a real zero.

**One y-axis, always.** Two measures of different scale on two scales make the
point where the lines cross an artefact of the axis ranges, and readers take a
crossing to mean something. Heart rate, cadence and elevation get a chart each;
training load rides in the weekly chart's *tooltip* rather than on a second
axis.

**An activity with no cadence sensor gets no cadence chart**, rather than a flat
line at zero — which would say the sensor read nothing rather than that there
was no sensor.

**Colours come from a validated palette**, assigned in fixed slot order and
never cycled. Every hue clears the lightness band, chroma floor, colour-vision
separation and normal-vision floor against its own surface. Two light-mode hues
fall below 3:1 on white, so anything painted with them carries a visible
label — identity is never colour alone. Dark mode is stepped separately from the
same ramps rather than being an automatic flip.

**Tooltip values wear text ink, not the series hue.** The dot beside a value
carries identity. Colouring the text is the default and puts a 2.7:1 green on a
white tooltip — the one place the palette's contrast warning actually bites.

**An axis narrower than its own labels is worse than no axis.** It drops the
leading character silently, so 110 minutes reads as `10m` and 28.8 km/h as
`8.8`. Both happened; both are now pinned by tests.

## The route

**There is no basemap.** Tiles would mean asking a third party for the map of
wherever you exercise, which is the opposite of the point of self-hosting. What
a bare line can still say is the shape of the ride and where on it you were
moving, so it says both.

**The line is coloured by speed**, in five steps of one hue, from the activity's
own slowest stretch to its fastest. Quantiles of *this* activity rather than
absolute bands: the question is where you were quick on this ride, and fixed
thresholds would paint a whole hike in one step. The legend names both ends in
the sport's unit, so the colours still read in absolute terms.

**If the two ends of the ramp would print the same figure, there is no ramp.**
Five shades of a number that does not change is decoration, so a steady ride
goes back to a plain line.

**A stretch whose speed is unknown is grey, not blue.** The app's single-series
blue happens to be the middle step of the ramp, so painting an unmeasured
stretch with it would read as "average pace" rather than "not measured".
Anything faster than 120 km/h counts as a lost fix, not a speed — deliberately a
speed ceiling and not a distance one, because samples arrive downsampled and
consecutive ones can legitimately be hundreds of metres apart.

**Start and finish are told apart by shape**, a disc and a square in text ink.
Green against red is the obvious choice and fails outright for a red-green
reader: those two sit 4.1 ΔE apart under simulated deuteranopia, where 8 is the
target. A route that finishes where it began gets **one** marker labelled as
both — two of them sat exactly on top of each other, and a loop is the commonest
shape of ride.

**The drawing is sized to the route, not to a square.** It used to be fitted
into a square and then letterboxed into a panel that is never square, so a broad
route was drawn at the height of the panel with half the width empty: a wide loop
used 42% of its panel and now uses 91%. The scale stays uniform either way —
shape is never distorted, only the space it is given changes.

## Heart-rate zones and load

**Zones are derived on request, not stored.** What is stored is the histogram —
how many seconds at each beat per minute — because zones hang off a maximum
heart rate that *moves*: one harder session and every previous activity's zones
shift. Stored zones would describe the athlete you used to be.

**To the beat, not to a band.** A five-beat bucket straddling a zone boundary
would hand its whole contents to one side of it.

**The maximum says where it came from.** Configured, or the highest beat any
activity recorded. Observed is a *floor* rather than a maximum: a peak nobody has
pushed to reads low and lifts every zone, so the panel prints which one it used
instead of asking you to trust it.

**Time below zone one is reported, never folded in.** Warming up and standing at
a junction are real time and not easy training; adding them to Z1 would inflate
exactly the zone people read as "I did my easy work".

**A gap longer than two minutes is not time at that heart rate.** It is a pause
or a lost signal, so it is dropped rather than credited — which is also why a
file sampled less often than that contributes no time in zone at all. The cost
is stated out loud rather than left to be discovered.

**Load is Edwards' TRIMP**: minutes in a zone weighted by the zone, one through
five. Banister's needs a resting heart rate and a sex-specific exponential this
app does not ask for; Edwards' needs only the zones already being computed.

## Fitness, fatigue and form

**The averages step once per calendar day, not once per activity.** A rest week
has to *lower* both, and walking the activities would skip exactly the days where
that happens — the lines would rise at every session and never fall between them.

**The decay is `1 - e^(-1/τ)`, not `1/τ`.** The two look interchangeable and are
7% apart at a seven-day constant, which compounds over a season into a fatigue
line that is visibly wrong.

**Form is *yesterday's* difference.** It answers "how fresh am I before today's
session"; using today's own figures would fold a session into its own readiness
score, so a hard morning would report that you were already tired setting out.

**The window is walked from the first activity ever**, and only the last N days
are returned. Starting the walk at the window would start both averages at zero,
so the first six weeks of every chart would show fitness climbing out of an
artefact of where the chart begins. A genuinely cold start still says so.

**An activity with no heart rate is counted out loud.** It earns no load, so it
does not merely go missing — it reads as a *rest day*, which lowers fatigue and
lifts form. A hard strapless week would otherwise look like a taper.

**Form shares one axis with fitness and fatigue.** The usual version of this
chart puts it on a second y-scale. All three are the same measure in the same
unit, so one axis is the honest one.

## Personal bests

**A best is the fastest stretch, not the average.** The 5 km best is the
quickest any five kilometres were covered inside any activity, found by sliding
a window over the samples — so a hard middle kilometre of an easy run is still a
record. The window is interpolated between samples, or the answer would depend
on how often the watch happened to write a point.

**Standing still and losing signal cannot set a record.** A pause adds time and
no distance; a hop longer than a plausible step adds time and no distance either.
Both would otherwise read as impossibly fast.

**Bests are computed at upload, not on request.** That is the one moment the
samples are already in memory. Answering later would mean re-reading every track
point of every activity for a figure that never changes.

**Window distances come from the positions, not from the file's own total.** A
wheel-measured total is the better number for the activity as a whole, but it
says nothing about *where inside* the activity a kilometre was, which is what a
window needs.

**A tie keeps the earlier activity.** Riding the same loop to the metre should
not move the date a record was set.

**Every record names the activity that holds it**, and opening it fetches that
activity: a figure with nothing behind it cannot be checked.

## Comparing two activities

**Against distance, not elapsed time.** Run the same route a minute slower and a
time axis pulls the two apart from the first hill, while a distance axis keeps
the hill in the same place — which is the whole reason for putting them together.

**Same sport only.** Comparing a run against a ride on a distance axis is
arithmetic nobody asked a question about, and offering it invites the comparison
rather than the pace of it.

**Both activities are resampled onto one grid.** Merging each track's own samples
into shared rows leaves a value for one activity and a gap for the other in every
row, so a chart that does not bridge gaps draws both lines shattered into
fragments exactly where they overlap. Where the shorter activity ends, its line
stops rather than being stretched to the length of the longer one.

**The comparison charts speak km/h for every sport**, unlike everywhere else. A
whole activity always moved, so its pace is a number; a single sample often did
not, and the pace of a standstill is unbounded — a minutes-per-kilometre axis
rendered its zero as a dash and read *faster* as it climbed. Pace stays where it
is well defined, in the summary above the charts.

**The two summary figures carry the colour of their line.** Two numbers stacked
under one label are anonymous otherwise, and the reader should not have to guess
which activity the second one belongs to.

## Narrow screens

**A wide table drops columns rather than scrolling behind a window.** The
activity table keeps date, activity and distance on a phone and earns sport and
time at `sm`, pace at `md`, climb and heart rate at `lg`. It already scrolled
inside its own box, which is the usual advice, but nine columns behind a 286px
window is a reader swiping to find a number they cannot see. Three they can read
beats nine they cannot, and nothing is lost: every hidden figure is in the CSV
export and in the activity itself.

**The sport survives its own column being dropped.** A coloured dot rides beside
the activity name below `sm`, with the sport in text for a screen reader — the
fact is kept even when the column carrying it is not, and identity is still
never colour alone.

**A grid item needs `min-width: 0` to be allowed to shrink.** Grid items default
to `min-width: auto`, so they refuse to go below their own min-content width and
push past the container instead. Every panel in the dashboard's two-column rows
came out 315px wide inside a 288px column at a 320px viewport.

**`overflow-x: auto` does not stop a table widening the page.** This one is
counter-intuitive and cost the most to find. Chromium lets a table descendant's
min-content width reach the initial containing block *through* a scroll
container, so the box scrolled correctly while the whole document also gained a
hard 754px floor — a phone user swiping sideways slid the entire layout off
screen and saw blank background. `contain: layout` on the scroller stops the
propagation without clipping anything; `overflow-x: hidden` on `html`, on `body`
and on the page container all changed nothing. That is why the `table-scroll`
utility exists instead of a bare `overflow-x-auto`.

**A flex item's width is fit-content, not "fill the parent".** The footer
turned the page into a `min-h-screen` column so it sits at the bottom on a
short screen rather than below the fold. That made the dashboard a flex item,
and a flex item takes its cross size from its content — so the activity table
pushed it to 339px inside a 320px column and dragged the document out with it,
the same 19px overflow the `table-scroll` utility had just been written to
stop. `*:w-full` on the column gives every child an explicit width and takes
the choice away. Third of a family now: a grid item needs `min-width: 0` to be
allowed to shrink, a flex item needs a width to be made to fill, and neither
default is the one a page layout wants.

**The app says where it came from, on every screen.** Somebody can arrive in
front of a running Activity Hub without having deployed it — a NAS in the
house, a server set up years ago — and the running app is then their only
clue, so the footer carries the link out to the project. Including on the
screen that reports an unreachable API: a person whose stack will not come up
is exactly the person who wants the repository, and that is where they are
stuck.

**A proportion bar that cannot show a proportion is decoration.** The zone rows
are three columns where there is room, and on a phone the bar drops to its own
line under the name and the time. Squeezed into a third of a 358px screen its
track was 150px, which put 20h07m and 15h48m a few pixels apart.

## Filtering, deleting, exporting

**Filter dates are local dates.** `date_from` and `date_to` are resolved in
`DISPLAY_TIMEZONE`, so asking for July returns July where you were, not July in
Greenwich. `date_to` is inclusive.

**The sport filter lists only sports you have recorded**, with counts, and the
counts stay unfiltered — narrowing the list should not make the options
disappear from under you.

**Upload results appear as each file lands**, with a running count. A few hundred
files used to mean minutes of silence, which is indistinguishable from a hang.

**Deleting asks twice.** There is no undo and the track points go with it, so the
destructive click is the second one — and Cancel is where Delete just was, so a
double-click cancels.

**The export is two formats because one is not enough.** GPX carries the samples
and has nowhere to put a device's own totals — a TCX states its distance and
average heart rate per lap, and a reader of the GPX has to recompute both from
the positions. So the CSV carries the figures this app stored and the GPX carries
the samples behind them. A test asserts the gap rather than leaving it to be
discovered.

**Downloads are links, not buttons.** The browser streams the file straight to
disk with the name the server chose; pulling the bytes into JavaScript first
would buy nothing and fall over on exactly the export big enough to matter.

**A GPX filename is the date, the sport and the id**, never the activity name. A
name can hold anything at all, and a zip full of files named after user input is
a zip nobody can unpack safely.

**An absent figure is an empty CSV cell**, and floats are rounded. `None` in a
spreadsheet is text that breaks every formula in the column, and
`12758.291778682977` metres reads as a bug rather than as a measurement.
