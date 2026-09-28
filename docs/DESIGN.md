# Interface redesign of the Social LLM-MAS Lab

Design proposal and record of what the redesign changed. The application is the companion laboratory of the paper
on outcome-based trust in a society of LLM agents: people sign in, create experiments from the paper's presets,
configure them, run them in replay or live mode, read the results and compare them with the pre-registered runs.

## 1. Information architecture

The experiment is the unit of work, so the structure follows the life of an experiment instead of listing
features side by side. Nine top-level tabs become a sidebar with five sections:

| Section | Pages | Purpose |
|---|---|---|
| Laboratory | Experiments | find, create, duplicate, rename, archive experiments; the only entry point |
| Open experiment | Configure, Replay, Live (role `live.run`), History | the workspace of one experiment |
| Reference | Presets, Paper comparison, Data and method | the paper's configurations, its numbers and the provenance of the data |
| You | Account | identity, role, password |
| Administration | Administration (role `users.manage`) | accounts, shared key and allowances, access log |

Pages of the workspace are always listed but, when no experiment is open, show one empty state with a single
call to action (go to Experiments). The sidebar keeps a persistent context card: the open experiment's name,
owner, origin preset, configuration version and whether the draft has unsaved changes; below it the signed-in
person and the sign-out button. Nothing else lives in the sidebar.

## 2. Navigation model

- `st.navigation` with `st.Page` callables, one Python module per page under `app/lab/views/`. Only the current
  page runs, which also removes the cost of rendering nine tabs on every interaction.
- Every page opens with the same header: a breadcrumb line (`Laboratory › Experiments`,
  `Experiments › paper-v2 (my copy)`), one title, one sentence of purpose and, when the page has one, the primary
  action on the right (New experiment, Save configuration, Run replay, Start live run).
- Workspace pages add a **context strip** under the header: experiment name, badges (`from Paper v2`, `v3`,
  `Unsaved changes` / `Saved`, `archived`, `read-only`), and one line of facts (owner, agents, schedule, runs,
  last update). The strip is filled at the end of the run so it reflects the edits of the current interaction.
- Actions that create or change an experiment (create, duplicate, rename, archive) are dialogs opened from the
  experiment card; each dialog has a cancel button and one primary button, and the destructive one (archive) is
  styled as such and explains what happens. Opening or creating an experiment switches to Configure; selecting a
  run in History switches to the page that shows it.
- Mode choices (task pool, discovery radius, key source) use radios or segmented controls; secondary detail
  (glossaries, ledgers, ground truth, calibration) sits in expanders; bulky reference material in expanders too.

## 3. Visual system

- **Type**: system sans-serif stack (no external font files); 16 px base; headings 1.75 / 1.375 / 1.125 rem,
  weight 650–600, tight leading; captions 0.85 rem in secondary ink. Numbers in tables are right-aligned with
  fixed decimals (rates `0.431`, points `+8.6`, USD `0.0578`).
- **Spacing**: cards (`st.container(border=True)`) are the grouping unit; 1 rem inner padding, 1 rem gaps; the
  page keeps Streamlit's content width; sections are separated by whitespace and a small-caps section title,
  not by rules.
- **Color roles** (from the validated chart palette already in the code): ink `#0b0b0b`, secondary ink
  `#52514e`, grid/border `#e6e5e1`, surface `#fcfcfb`, sidebar `#f4f3ef`, primary (actions, links, focus)
  `#2a78d6`. Chart series keep their fixed slots (`#2a78d6 #eb6834 #1baf7a #eda100 #e87ba4 #008300 #4a3aa7`)
  and their dashes and markers, so identity is never color alone.
- **Status colors**: the theme's green (saved, reachable, matches current configuration), orange (unsaved,
  earlier configuration, dataset missing), red (errors, destructive actions), blue/gray (informational badges).
  Every status carries a word or an icon; color only reinforces it.
- **Tables**: human column labels (`Success`, `USD / 1,000 episodes`, `Unreliable, first window`), number formats
  through `column_config`, no index, no raw `snake_case`.
- **Charts**: unchanged Plotly figures (line charts with markers and dashes, forest plot of paired differences,
  stacked selection shares, competence map), on the same surface color as the page.
- **Theme file** (`.streamlit/config.toml`): light base, primary color, background and sidebar colors, border
  color, 0.5 rem radius, heading sizes and weights, dataframe header color, categorical chart colors. A short CSS
  block adds what the theme cannot express: breadcrumb style, context strip background, destructive button,
  denser metric tiles.

## 4. Anatomy of the key screens

**Experiments.** Header with the primary action *New experiment*. A toolbar with a name/owner filter and a
*Show archived* toggle. One card per experiment: name and badges on the first line; owner, size of the
population, schedule, number of runs and last update on the second; the latest replay headline on the third
(`social (full) 0.431 · random 0.345`). At the right of the card: *Open* (primary) and a *More* popover with
Duplicate, Rename and Archive/Restore according to permissions. Empty state: a card that explains what an
experiment is and offers *Create the first experiment*. The *New experiment* dialog shows the preset, its
description and the name.

**Configure.** Context strip, then cards in reading order: *Origin* (the differences from the origin preset, or
"identical"), *Population* (data editor with labelled columns and a profile glossary), three columns of rule
cards (*Tasks and declarations* + *Graph and discovery*, *Selection*, *Trust* + *Analysis*), *Run settings*
(seeds, episodes, policies, bootstrap resamples, policy glossary) and *Notes*. A closing action bar holds the
state (validation problems, unsaved, saved) on the left and *Discard changes* / *Save configuration* on the
right; import and export of the JSON sit in an expander below it. Read-only visitors see the same page with
disabled widgets and a `read-only` badge.

**Replay.** Context strip; a *Run* card with the saved schedule, the time estimate and *Run replay*; then the
results of the selected run: a run picker with the "matches the current configuration" status, a headline row of
four tiles (best social policy vs random in points, unreliable share first → last window, seeds × episodes ×
policies, elapsed time), the headline table, the forest plot, the four time-series and selection charts, the
decline table, and the calibration and ground-truth expanders; downloads at the end.

**Live.** Context strip; status cards for the grader and the task dataset (with *Fetch dataset*); a *New live
run* card with schedule, quote and the form (key source, key, cap, *Start live run*); the reference of the
paper's live validation in an expander; then the selected live run: tiles (status, real calls, upper cost vs
cap, social − random), policy and base-model tables, success by window, calls ledger, downloads.

**History.** Context strip; tiles (runs, replay, live, live spending); one table of every run with plain
labels; a picker with *Open this run*, which selects the run and switches to Replay or Live.

**Presets.** Overview table of the six read-only presets, then the chosen one in full: tiles, differences from another preset (a variant against its main run by default), population, every rule and run setting with its JSON key, policies, and the pre-registered headline. Actions: create an experiment from it (opens the New experiment dialog prefilled), open its results on Paper comparison, download the JSON.

**Paper comparison.** Reference picker, tiles and tables of the pre-registered run, the v3 liars block, and,
when the open experiment has a replay run, a card comparing it with the reference on shared seeds.

**Account and Administration.** Account: a profile card (name, id, role badge, capabilities) and the password
form. Administration: three tabs, *Accounts* (table, add, edit), *Shared key* (status, set/remove, global cap,
spending), *Access log*.

## 5. What changed versus the current app, and why

- Tabs → sidebar navigation with sections and one page per run: the tab bar mixed the list, the workspace, the
  references and the administration at the same level, and rendered all of them on every interaction.
- Selectbox + row of loose buttons → experiment cards with a primary action and a grouped menu; create, duplicate,
  rename and archive moved into dialogs with explicit confirmation, so the list stays readable and destructive
  actions are deliberate.
- A context strip and the sidebar card replace the scattered captions that said which experiment was open and
  whether it had unsaved changes; the information is now in the same place on every page.
- Forms are grouped in titled cards with help text instead of bare columns; the save/discard bar closes the
  Configure page with its validation state next to the buttons.
- Results open with metric tiles that answer the paper's questions first (gain of the social policy over random,
  decline of unreliable selections, cost of live runs); tables got plain labels and formats.
- Empty states explain what to do next instead of showing an empty table.
- Behaviour, permissions and what is recorded are unchanged: the engine, the experiments store and the access
  control under `socialmas/` were not touched; the UI tests keep every check and were adapted to the new
  selectors (pages instead of tabs, dialogs, cards).

## 6. Guided help and expert mode

Newcomers get a guided layer: every page title, card title, metric tile, chart, table (and its columns) and form
field that needs explaining carries a native tooltip (the ⓘ icon), one or two plain sentences on what the item is
and how to read it, grounded in the engine's docstrings, the README and the glossaries. The texts live in one module,
`app/lab/help.py`, as a dict of keys (`configure.seeds`, `replay.metric.social_vs_random`, ...) and every call site
asks `ui.help("key")`; charts and tables that have no `help=` parameter get a small "How to read this" caption that
carries the tooltip. An **Expert mode** toggle in the sidebar (below the signed-in person, above the context card)
switches the whole layer off: `ui.help` then returns `None`, so the same call sites render without tooltips; the
toggle keeps a caption that says what it does. The state is kept in `st.session_state` for the browser session. A
test checks that a known widget carries its text in guided mode and none after the switch, and that every key the
pages ask for exists and every text is used.

Known limits: light theme only (the chart palette is validated for light surfaces); the experiment list is a
single column of cards, adequate for a laboratory with dozens of experiments, not thousands; the expert mode choice
is per session, not per account (persisting it would need a small settings accessor in `socialmas.access`, which
was deliberately left untouched).
