# Feature Specification: Controlled Power and Fleet Downtime

**Feature Branch**: `spec/042-controlled-power-and-downtime`

**Created**: 2026-11-17

**Status**: **Draft for owner review. No implementation in this
change.** The verified current state this draft stands on is
recorded in the Phase 1 state report (Desktop Access chat,
2026-11-17) and summarized in "Where this starts" below —
including two places where the field's picture of spec 011
was stale and the record corrects it.

**Direction (owner, 2026-11-17 07:53 ET, Fleet umbrella
chat)**: "make sure we have syncyard controlling controlled
reboots and shutdowns and perhaps other adjacent things. add
these to syncyard and any skills.md for it and make sure once
done and tested, all agents are aware also if a machine goes
down, anyone who detects it should make sure the entire fleet
is aware of this downtime and some sort of recovery attempt
should be made in hopes it was jammed and gets unjammed — but
ultimately a fix may require physical presence and
intervention."

This spec closes the two halves of that order:

1. **Syncyard-initiated power control.** Spec 011 gave
   Syncyard protection when *someone else* shuts a host down
   (delay + drain + checkpoint + notify), and its Amendment 1
   added one initiated verb — `gk reboot` — built in the
   Windows-desktop era. The fleet has since converted to
   Linux; the verb's routes are Windows-shaped, it has no
   power-off, no cancel, no schedule, and nothing verifies
   the host came back. This spec generalizes initiated power
   control across the fleet as it exists now.
2. **Fleet downtime awareness and recovery.** Today a host
   going down is visible in `gk status` and nowhere else
   unless a human notices. There is no fleet-visible downtime
   record, no recovery attempt, and no escalation state.
   This spec adds the record, the bounded recovery ladder,
   and the physical-presence escalation the owner ordered.

**The honesty envelope, inherited from spec 011 and
unchanged**: Syncyard can *delay + drain + checkpoint +
notify*. It cannot *prevent* — not a forced shutdown, not a
power loss, not a held power button. Every requirement below
is written inside that envelope. A power verb that reports
success because its signal was *sent* is a defect under this
spec: the payload verdict rule (spec 020, standing fleet
rule) governs every action here — the verdict is the
observed outcome on the host, never the wrapper's exit.

## Where this starts (verified 2026-11-17, first-hand)

- **Spec 011 is merged and substantially built.** PR #29
  (spec, 2026-10-31), PR #33 (Phase 1: liveness record,
  going-down ingest, outbox notify, 2026-10-31), and PR #42
  (Phases 2–3: `gk drain` + the shutdown guard,
  2026-11-02) are all merged to main. The umbrella picture
  of PR #42 as "stacked/open/unmerged" is stale; the drain
  and guard code is on main today.
- **`gk reboot` exists** (spec 011 FR-015, T021, commit
  200c5bb, 2026-11-01): drain-aware refusal naming active
  jobs, the going-down record written before any signal
  (trigger `remote-reboot`), a `host_reboot_requested`
  ledger event naming the requesting chat, then the signal —
  backchannel route first (Windows `shutdown.exe /r` invoked
  through the host's WSL2 distro), maintenance dispatch
  second (a PowerShell `shutdown.exe` job), an honest
  `REBOOT UNREACHABLE` otherwise. It has **never been
  live-fired** (spec 011 T022 is still open).
- **The drain machinery exists and is the reuse path**:
  `gk drain --host <host>` signals running
  checkpoint-capable jobs through spec 013's FR-008 hold
  files (`_request_checkpoint_hold`, the same path `gk hold`
  uses), sets a per-host drain hold in the liveness record,
  waits the per-lane window (config `drain.window_s`,
  default 120 s, plus `drain.per_lane_window_s`), and prints
  a per-job verdict (CHECKPOINTED / FINISHED / ENDED /
  UNCHECKPOINTED) classified from the sweep's own harvest.
  `gk host-resume <host>` clears both host holds. The
  going-down record is a JSON object — `host`, `ts`,
  `trigger` (`shutdown | logoff | update | unknown |
  remote-reboot`), `active_run_ids`, `supervised`
  (`{id, checkpoint}` list), `uncheckpointed` (id list) —
  written host-side with verified-write discipline, merged
  by the backchannel agent into the heartbeat payload as
  `going_down`, and ingested by the sweep exactly once per
  (host, ts): ledger `host_going_down`, per-job
  `interrupted_by: host-shutdown` annotations, a dispatch
  hold, and outbox pushes to the affected jobs' registered
  notify targets.
- **Host liveness exists**: the sweep keeps a per-host
  last-seen record (`hosts.json`), `gk status` renders
  UP/DOWN against `liveness.down_after_s` (default 900 s),
  and a stopped Windows guard ledgers `guard_stale` /
  `guard_recovered` exactly once per transition.
- **What does not exist** (the gaps this spec closes):
  - power-off / shutdown as an initiated verb; cancel of a
    pending power action; any scheduled power action beyond
    `gk reboot`'s grace delay;
  - any initiated power route for a **Linux host** — both of
    `gk reboot`'s routes end in Windows `shutdown.exe`, and
    every fleet host in service today runs Linux or macOS;
  - boot-back verification: spec 011's FR-010 recovery
    handshake is unbuilt (T014 open), so after a signal
    nothing checks the host returned, and there is no
    failure state when it does not;
  - the Windows guard is **built but undeployed** (spec 011
    T008 open; source battery only, never compiled in the
    field), and its owner oracle evidence (T005/T006) is
    still owed — with no Windows host left in the fleet, that
    deploy is dormant, not pending;
  - spec 011's reconciliation and recovery report (T015 /
    T016) are unbuilt, so an interrupted run's final account
    is still assembled by hand;
  - a fleet-visible **downtime record**: the going-down
    outbox push reaches only per-job notify registrations
    (spec 011's tasks name the missing owning-chat route as
    an open gap), and an *unplanned* disappearance — crash,
    power loss, network loss — produces no record at all;
  - a **recovery ladder**: nothing re-probes a down host
    across independent channels, attempts a wake, or retries
    anything; and **Wake-on-LAN exists nowhere** in the
    codebase (zero implementations; spec 039 FR-MAC-05
    explicitly promises no WoL for the Mac).

## Boundaries with neighboring specs

- **Spec 011** owns shutdown *protection* (externally
  triggered) and the drain/checkpoint machinery. This spec
  consumes that machinery unchanged — it adds no second
  drain, no second hold, no second going-down format. Spec
  011's open field tasks (T008 guard deploy, T011/T013 boot
  conversion, T014 handshake, T022 live fire) stay spec
  011's; where this spec needs one of them (the handshake,
  for boot-back verification), it names the dependency and
  defines an interim verification that is honest about being
  interim.
- **Spec 040 (host self-recovery, draft)** owns the Syncyard
  *stack* dying while the host is alive (agent freeze,
  runner death, self-repair). This spec owns the *host's*
  power state and the host-down case. The ladder's lesser
  step (Part B, FR-009) invokes stack-level restart as an
  operator action; the self-repair internals are spec 040's.
  A detector that finds the host alive but the stack dead is
  a spec 040 event, not a downtime incident under this spec.
- **Spec 039 (macOS host)** owns the Mac's availability
  honesty: a sleeping Mac is unavailable, no WoL promise,
  sleep interruptions named not failed. This spec does not
  override any of that (Part D exceptions).
- **Spec 020 (payload verdict)** governs every verdict in
  this spec. **Spec 010 FR-009 (dispatch-only invariant)**
  is untouched: power signals ride the existing backchannel
  and maintenance-dispatch routes, and no component gains a
  new way to start runner jobs.

## User scenarios

1. **Planned reboot of a Linux host.** The operator runs one
   command. Syncyard accounts for the host's active jobs,
   drains or refuses, writes the record, signals the reboot,
   holds dispatch, and then *verifies the return*: heartbeat
   fresh, host health record updated, runners back per their
   labels. The action record closes with a verdict, not with
   "signal sent."
2. **Power-off for hardware work.** The operator powers a
   host down deliberately. The same discipline runs, the
   host's expected state becomes DOWN-BY-ACTION (no downtime
   incident is raised — the fleet was told), and the record
   waits for a human to power the host back on.
3. **A host vanishes at 03:00.** No going-down record
   arrives; the heartbeat ages past the threshold. One
   downtime record opens, the fleet chats are told once, the
   recovery ladder runs its bounded course, and the record
   either closes as recovered-by-ladder (naming the step
   that worked) or flips to NEEDS PHYSICAL PRESENCE with a
   named owner and an on-site checklist. Nobody's chat gets
   the same alarm twice.
4. **The jammed host.** A host's OS is alive on one channel
   but its Syncyard stack is wedged. The ladder finds the
   live channel, restarts the stack (the lesser step), and
   only if that fails spends its one controlled reboot.
   Recovery is claimed only when the host's own heartbeat
   and health record answer again — never because a
   different channel showed a pulse.
5. **The roaming laptop goes quiet.** laptop-bench or
   air-inference stops reporting because it is in a bag, on
   a plane, or asleep. Nothing happens: no record, no
   ladder, no alarm. Their silence is expected by design.

## Requirements

Each requirement carries a behavior statement, an acceptance
mode (**test** = an automated battery decides; **oracle** =
the owner or operator judges from presented evidence;
**gate** = a named human decision must precede the act), and
a *this does not establish* line bounding what passing it
proves.

### Part A — Initiated power actions

- **FR-001 — One power verb family, every fleet OS.**
  *Behavior*: the gatekeeper gains a power verb family over
  the existing `gk reboot`:
  `gk power --host <host> --action <reboot|poweroff|cancel>`
  with `--at <time>` or `--delay <seconds>` for scheduling,
  `--requested-by <chat-id>` required, and `--force` /
  `--override-reason <text>` for the override path (FR-004).
  `gk reboot` remains as a compatibility alias for
  `--action reboot` with its current semantics. Routes are
  per-OS and selected exactly as `_reboot_route` selects
  today — a route that *proves the host* (a fresh backchannel
  heartbeat naming the host, else an online runner of the
  host) — extended with per-OS signal bodies:
  Linux: `systemctl reboot` / `systemctl poweroff` issued
  through the backchannel agent's host shell or a linux.yml
  maintenance dispatch; Windows: `shutdown.exe /r|/s`
  through the routes spec 011 already built; macOS: **no
  initiated power action in this spec** (Part D — the Mac is
  an opportunistic, roaming node; its shape is designed and
  stated, not built). A host with no live route gets the
  honest unreachable result (`POWER UNREACHABLE`, ledgered,
  exit nonzero), never a queued hope.
  *Acceptance*: test — fixture batteries pin route selection,
  per-OS signal bodies, the unreachable path, and the alias's
  byte-identical behavior against the spec 011 battery; the
  Linux body is additionally proven live in the test plan's
  field leg.
  *This does not establish* that a signaled host obeyed —
  obedience is FR-005's boot-back / confirmed-down verdict,
  and a signal without it closes as UNVERIFIED, not DONE.

- **FR-002 — Power-off is a first-class action, gated
  harder than reboot.**
  *Behavior*: `--action poweroff` runs the same drain
  discipline as reboot (FR-003) and additionally requires an
  explicit per-action confirmation: the command must carry
  `--confirm <host>` repeating the host name, and the action
  record names the requesting chat and the confirmer. On
  acceptance the host's expected state is set to
  DOWN-BY-ACTION *before* the signal, so the downtime
  machinery (Part C) never raises an incident for a planned
  power-off, and the fleet-status surface shows the host as
  intentionally down with the action's id. The verdict for a
  power-off is CONFIRMED-DOWN: the host's heartbeat and
  runners observed silent for a full confirmation window
  (config `power.confirm_down_s`, default 180 s) after the
  signal.
  *Acceptance*: test — the battery pins the missing-confirm
  refusal, the expected-state-before-signal order, and the
  CONFIRMED-DOWN window logic on fixtures.
  *This does not establish* that the host is electrically
  off — only that every Syncyard channel observed it down
  for the window; the record says exactly that.

- **FR-003 — Drain before signal, always, reusing spec
  011's machinery.**
  *Behavior*: every initiated action first accounts for the
  host's active jobs exactly as `gk reboot` does today
  (submitted / dispatching / dispatched on the host's
  lanes). With active jobs and no override, the action
  refuses and names them — the polite path is `gk drain
  --host` (spec 011 FR-007, unchanged) or waiting. When the
  operator elects to proceed after a drain, the power verb
  invokes the same drain path (hold files via spec 013
  FR-008, drain hold, per-lane window, per-job verdicts) and
  carries the drain's verdict into the action record; a job
  the drain left UNCHECKPOINTED is named in the record, never
  smoothed. The going-down record is written before any
  signal (trigger `remote-reboot` for reboot; `remote-poweroff`
  joins the trigger vocabulary for power-off), through spec
  011's existing ingest, so the dispatch hold, annotations,
  and outbox pushes are Phase 1 semantics exactly.
  *Acceptance*: test — the battery pins refusal-with-active,
  drain-then-signal order, and record-before-signal order
  for both actions, reusing the spec 011 golden scenarios
  where they already pin the shared halves.
  *This does not establish* that a checkpointed job resumes
  correctly — resume sufficiency remains the job's own
  contract, as spec 011 states.

- **FR-004 — The override is explicit and recorded.**
  *Behavior*: `--force` skips the active-job refusal only
  when the invocation also carries `--override-reason
  <text>` and `--requested-by <chat-id>`; all three are
  written into the action record and the ledger event. An
  override never skips the going-down record, the drain
  *accounting* (the record still names every job the action
  will interrupt), or the audit trail — it skips only the
  wait. There is no config setting that pre-authorizes
  overrides, and no chat message, relayed or otherwise,
  substitutes for the flags on the command that acts.
  *Acceptance*: test — force without a reason refuses;
  force with a reason ledgers all three fields byte-for-byte
  in the golden battery.
  *This does not establish* owner intent for any given
  override — the record proves who asked and what reason was
  given; judging the reason remains a human act.

- **FR-005 — Boot-back verification, with a failure state.**
  *Behavior*: a reboot action opens an expected-return
  window (config `power.return_window_s`, default 900 s)
  when the signal is sent. The action closes VERIFIED only
  when, inside the window, the host proves itself back by
  *served identity*: a fresh backchannel heartbeat naming
  the host, the host's liveness record updated by the sweep,
  and — when spec 011's FR-010 recovery handshake exists
  (T014) — a handshake matching the action's going-down
  record. Until T014 lands, the interim identity is
  heartbeat-fresh + runner-state-per-labels, and every
  action record closed on the interim identity says so.
  Window expiry without identity closes the action as
  RETURN-MISSED and opens a downtime record (Part C) with
  the action as its detector — the fleet hears about a
  reboot that did not come back from the action record, not
  from someone noticing silence. A host returning *after*
  the window still verifies, and the record amends to
  VERIFIED-LATE with both timestamps.
  *Acceptance*: test — fixture hosts returning inside,
  outside, and never close as VERIFIED, VERIFIED-LATE, and
  RETURN-MISSED respectively, with the downtime record
  opening exactly once in the never case.
  *This does not establish* job-level health on the returned
  host — presence and identity are proven here; the next
  jobs' markers prove health, as always.

- **FR-006 — Cancel is a real verb with a bounded claim.**
  *Behavior*: `--action cancel` aborts a *pending* action:
  a scheduled (not yet signaled) action is withdrawn
  outright — ledgered, record closed CANCELLED, fleet-status
  surface cleared. A signaled-but-still-in-grace action is
  canceled through the OS's own abort where the platform
  offers one (Windows `shutdown /a`; Linux `shutdown -c`
  for `shutdown`-scheduled actions) over the same route that
  signaled it; where the signal was an immediate `systemctl`
  action with no abort handle, cancel reports
  NOT-CANCELLABLE with the reason, in those words. Cancel
  never claims success from the abort command's exit code:
  the verdict is the host's observed state afterward (still
  up past the action's fire time = CANCELLED-CONFIRMED;
  went down anyway = CANCEL-FAILED).
  *Acceptance*: test — scheduled-withdrawal, in-grace abort,
  and not-cancellable paths pinned on fixtures per OS route;
  the Linux in-grace path proven in the field leg.
  *This does not establish* a cancel path for actions other
  components signaled — cancel governs Syncyard's own
  pending actions only.

- **FR-007 — The audit record is the action.**
  *Behavior*: every initiated action writes one action
  record (JSON, verified-write, beside the queue) carrying:
  id, host, action, requested-by, confirmer (power-off),
  override fields when present, scheduled/fire times, route
  selected and its evidence, the drain verdict and the
  going-down record's (host, ts) key, signal result, and the
  closing verdict in this spec's vocabulary (VERIFIED /
  VERIFIED-LATE / RETURN-MISSED / CONFIRMED-DOWN /
  CANCELLED-CONFIRMED / CANCEL-FAILED / NOT-CANCELLABLE /
  UNREACHABLE / REFUSED / UNVERIFIED) with the timestamps
  that back it. Ledger events mirror the record's transitions
  (`host_power_requested`, `host_power_signaled`,
  `host_power_verified`, `host_power_return_missed`,
  `host_power_confirmed_down`, `host_power_cancelled`,
  `host_power_refused`, `host_power_unreachable`). A record
  that never reaches a closing verdict is itself an ISSUES
  entry on `gk status` — an open power action is never
  invisible.
  *Acceptance*: test — the golden battery pins the record
  shape and one full lifecycle per closing verdict.
  *This does not establish* anything beyond the record's own
  fields — the record is the evidence, and fields it does
  not carry were not observed.

### Part B — Adjacent controls (in and out, named)

- **FR-008 — Power/status query is a first-class fleet
  record. IN.**
  *Behavior*: the per-host liveness record gains a power
  section, rendered by `gk status` and carried in the
  fleet-status snapshot: `power_state` ∈ UP / DOWN /
  DOWN-BY-ACTION / REBOOTING (action open) / RETURN-MISSED /
  UNKNOWN, `last_action` (id, action, verdict, ts),
  `last_seen_alive`, and `expected_return_by` while a reboot
  window is open. The snapshot the tray and dashboard read
  shows the same states — a planned-down host and a crashed
  host never render identically.
  *Acceptance*: test — status and snapshot batteries pin each
  state's rendering from fixture records.
  *This does not establish* real-time truth — the record is
  as fresh as the sweep that wrote it, and renders its age.

- **FR-009 — Stack restart is the lesser step, and it is a
  verb. IN.**
  *Behavior*: `gk host-restart --host <host>` restarts the
  host's Syncyard stack — runners and backchannel agent —
  without touching the OS, over any live route that proves
  the host. It is the ladder's (Part D) first active step
  and an operator verb in its own right. Its verdict is the
  stack's own answer afterward: heartbeat fresh and runner
  states re-read, per component, so "agent back, runners
  still dead" is a possible and reportable outcome. The
  self-repair internals a restart triggers on the host are
  spec 040's; this verb is the operator/ladder surface that
  invokes them.
  *Acceptance*: test + the field leg's jammed-host drill
  (test plan) — a wedged-stack fixture recovers by this verb
  alone, with per-component verdicts.
  *This does not establish* that a stack restart fixes an OS
  level jam — that is what the ladder's later steps are for.

- **FR-010 — Wake attempts where the platform supports
  them. IN, per-host configured.**
  *Behavior*: a host may carry a `wol` config block
  (`mac`, `via` — the LAN-resident fleet host that sends the
  magic packet, `enabled`). A wake attempt is: the `via`
  host sends the magic packet to the target's MAC on its
  LAN, logged with sender, target, and time. Wake is an
  *attempt* — its verdict is only ever the target's
  subsequent boot-back identity (FR-005), never the send.
  Hosts without a `wol` block, hosts whose NIC/BIOS cannot
  wake, and hosts with no LAN-resident sender simply have no
  wake step; the ladder (Part D) records WOL-NOT-CONFIGURED
  and moves on. macOS: no wake step exists (spec 039
  FR-MAC-05 — no WoL promise for a sleeping Mac), and this
  spec adds none.
  *Acceptance*: test for the config validation and the
  ladder's use of the step; oracle for any field wake — a
  wake is proven only by the host returning, observed.
  *This does not establish* that a configured host *can*
  wake — BIOS/firmware posture is a field fact per host,
  recorded in the host's record when first proven or first
  failed, and the record distinguishes CONFIGURED from
  PROVEN.

- **Out of scope, named**: sleep/suspend as an initiated
  action (no fleet need stated; roaming hosts sleep on their
  own policy); power control over layer1labs-inference
  (Part D exception — not a venue, not on the fleet tailnet);
  any power action on a host while its venue conversion or
  guard deploy is mid-flight (the pause-first discipline
  governs, as today); UPS/power-source management; remote
  power for a host with no Syncyard route at all (FR-001's
  honest unreachable is the whole story there).

### Part C — Downtime detection and the fleet record

- **FR-011 — One record per incident, deduped by
  construction.**
  *Behavior*: when a detector concludes a fleet host is
  down, the gatekeeper opens ONE downtime record keyed
  (host, incident-open ts). Detectors: the sweep's liveness
  transition (heartbeat age past `liveness.down_after_s`
  with no DOWN-BY-ACTION expected state), a missed
  expected-return window (FR-005), a going-down record whose
  host does not return and was not an initiated action, and
  an operator filing by hand (`gk downtime --host <host>
  --note <text>`). Every later detector that finds the same
  host still down *appends evidence to the open record* — it
  never opens a second one, and no transition out of the
  open state repeats a notification already sent for that
  transition. The record closes exactly once: RECOVERED
  (with the closing evidence), or superseded by
  NEEDS-PHYSICAL (FR-014) which is a state of the same
  record, not a new one.
  *Acceptance*: test — multi-detector fixtures converge on
  one record; re-sweeps and repeat filings add evidence
  lines and zero duplicate notifications.
  *This does not establish* that two genuinely separate
  outages can never share a record — a host that recovers
  and falls again closes and reopens by the state machine,
  and the battery pins that too.

- **FR-012 — The record's fields, and class from evidence
  only.**
  *Behavior*: a downtime record carries: host; first-detected
  (ts + detector); last-seen-alive (the liveness record's
  timestamp, named as such); detector chain (every detector
  that contributed, in order); class; jobs affected (the
  gatekeeper's own records for the host at detection:
  active runs interrupted, queued runs waiting, each named);
  ladder log (Part D, appended as it runs); state (OPEN /
  LADDER / RECOVERED-BY-LADDER / RECOVERED-UNASSISTED /
  NEEDS-PHYSICAL / CLOSED); and the closing account. Class
  is assigned only from evidence, by named rules:
  a going-down record for the window → ORDERLY (with its
  trigger); an initiated action open → BY-ACTION (normally
  no incident at all — FR-002); tailnet peer offline while a
  LAN-resident prober still reaches the host → NETWORK;
  heartbeat lost mid-job with no going-down record and no
  channel answering → CRASH-OR-UNKNOWN, rendered UNKNOWN
  with the evidence lines attached. No class is ever
  upgraded on a guess; UNKNOWN is a respectable final class.
  *Acceptance*: test — one fixture per class rule, including
  the refusal to classify beyond the evidence.
  *This does not establish* the physical cause of an outage —
  class is a statement about what Syncyard observed, and the
  record's evidence lines are the whole basis.

- **FR-013 — The fleet is told, once per transition, in
  four places.** *(Push scope narrowed by the owner's
  2026-11-17 ruling, decision 4 below: pushes go to the
  main chat on ESCALATION ONLY; open and close are
  record-only. The ruling governs where it differs from
  the text below.)*
  *Behavior*: opening a record, flipping to NEEDS-PHYSICAL,
  and closing a record each produce exactly one outbox push
  to each of: the Syncyard chat (owner of record), the Fleet
  umbrella chat, the affected machine's own chat, and the
  main chat — via standing downtime notify registrations in
  config (a per-host chat map), which is the general form of
  the owning-chat route spec 011's Phase 1 named as missing.
  Ladder progress does not push; it accrues in the record,
  readable in `gk status` and the snapshot. A push names:
  machine, state, first-detected, last-seen-alive, class,
  jobs affected count, and the record id — enough to act on
  without opening anything.
  *Acceptance*: test — the battery pins one push per target
  per transition, zero on re-sweep, and the push body fields.
  *This does not establish* delivery to human eyes — the
  outbox's delivered-on-ack semantics remain the delivery
  record, as spec 011 FR-004 states.

### Part D — The recovery ladder

- **FR-014 — A bounded, logged ladder, run before anyone
  is sent to a machine.**
  *Behavior*: on record opening (except BY-ACTION and the
  exception hosts, FR-016), the ladder runs, each step
  logged to the record with its evidence and timestamp:
  (1) **Re-probe all independent channels**: backchannel
  heartbeat age; runner states via the door repo's API (one
  read, on the sweep's existing discipline); the Syncyard
  agent channel for the host where one exists; RustDesk
  rendezvous presence where the fleet's server records it;
  a LAN probe only from a fleet host resident on the same
  LAN, where one exists. (2) **Wake attempt** where FR-010
  configures one. (3) **Wait + re-probe with backoff**:
  re-probes at +2, +5, +10 minutes (config
  `downtime.ladder_backoff_s`), any of which can close the
  incident as RECOVERED-UNASSISTED if the host's own identity
  answers (FR-005's identity standard — never another
  channel's liveness alone). (4) **Lesser step**: if any
  channel proves the host alive but the stack is down,
  `gk host-restart` (FR-009) over that channel, then a
  re-probe. (5) **One controlled restart**: only if a
  channel that can carry a power signal is *actually alive*
  (the FR-001 route proof), one `gk power --action reboot`
  under this spec's discipline — drain accounting included,
  the record naming every job it interrupts — then the
  FR-005 return window. The ladder's total bound is config
  `downtime.ladder_budget_s` (default 1800 s); at budget
  expiry with the host still down, the record flips to
  NEEDS-PHYSICAL (FR-015) and active steps stop. Every step
  is bounded, none retries silently, and the ladder never
  spends a second restart.
  *Acceptance*: test — fixture hosts scripted per outcome:
  answers at step 1 (no incident escalation), wakes at
  step 2, returns during backoff, stack-restarts at step 4,
  reboots at step 5, and never returns (budget expiry →
  NEEDS-PHYSICAL) — the ladder log and the closing state
  pinned for each.
  *This does not establish* that the ladder fixes any
  particular real outage — it establishes that the attempt
  is bounded, ordered, lesser-first, and fully logged, which
  is what the owner's order asks the mechanism to guarantee.

- **FR-015 — NEEDS PHYSICAL PRESENCE is a state with a
  name, an owner, and a checklist.**
  *Behavior*: the flip writes into the record: the named
  owner of the physical step (Tristen for fleet hosts; Ryan
  Anderson for layer1labs-inference, whose record path is
  FR-016), the on-site checklist for the host's class —
  power source and cable, power-button state, display/console
  first screen, network cable and dock where the host has
  one (laptop-bench's wired NIC lives on its Thunderbolt
  dock), obvious damage or theft — and the ladder's full log
  as the "already tried" account, so the human never repeats
  a step blind. After the flip, automated action stops
  except a slow re-probe (config `downtime.slow_reprobe_s`,
  default 3600 s) whose only powers are to notice a return
  and close the record RECOVERED-UNASSISTED with the
  boot-back identity check. The flip pushes per FR-013.
  *Acceptance*: test — the flip's record contents and the
  slow-reprobe-only posture pinned on fixtures.
  *This does not establish* that the named owner is
  available or nearby — the record names who the step
  belongs to; reaching them is a human act the push enables.

- **FR-016 — Roaming and off-fleet exceptions are hard
  rules, not tuning.**
  *Behavior*: hosts flagged `roaming: true` in config —
  **air-inference and laptop-bench** — never open a downtime
  record, never run a ladder, and never push a downtime
  notification, at any silence length. Their resources are
  exemption-only: a job that needs them waits or fails on
  its own terms, exactly as today. **layer1labs-inference**
  is not a dispatch venue and is not on the fleet tailnet:
  no ladder runs against it and no power verb targets it;
  if its own chat or the owner reports it down, an operator
  may file a record by hand (FR-011) whose escalation owner
  is Ryan Anderson and whose ladder is limited to the
  re-probe step over whatever channel reported it. Removing
  a host from the exception set is a config change with the
  owner's name on it, never a default flip.
  *Acceptance*: test — roaming fixtures silent for 72
  simulated hours produce zero records, zero pushes, zero
  ladder steps; the hand-filed layer1labs-inference record
  carries the right owner and the limited ladder.
  *This does not establish* that a roaming host is *well* —
  only that its silence is not an incident; its own chat
  remains free to care, through its own channels.

### Part E — Safety rails (standing fleet rules, restated as requirements)

- **FR-017 — Windowless, PowerShell 7, parse-gated,
  explicit cwd.**
  *Behavior*: every host-side element this spec adds obeys
  the standing rails: no visible console window on any owner
  machine, ever (hidden launches by construction, as spec
  007/032 enforce); PowerShell 7 only on every Windows
  surface; every PowerShell job script passes the real
  parser with zero errors before submission (a parse error
  is NO VERDICT, never a pass); every run.yml submission
  passes `--cwd` explicitly (standing interim rule). The
  Linux signal bodies are shell through the agent/runner
  surfaces that already run windowless by construction.
  *Acceptance*: test — the source batteries that guard the
  existing rails cover the new surfaces by name.
  *This does not establish* rail compliance of components
  this spec does not touch — their own batteries govern them.

- **FR-018 — API and action discipline.**
  *Behavior*: GitHub API polling anywhere in this spec's
  machinery honors the fleet discipline (3–5 minute minimum
  intervals, one watcher per run, 403 is a hard stop for the
  scope); the ladder's runner-state reads ride the sweep's
  existing reads wherever the sweep is the actor, and any
  ladder read beyond them is counted in the record's log.
  No power action runs against a host with running jobs
  except through FR-003's drain or FR-004's recorded
  override. No component in this spec dispatches work to a
  host in an open power action or an open downtime record
  except the ladder's own steps.
  *Acceptance*: test — read-count assertions in the ladder
  battery; the dispatch-hold interaction pinned against the
  spec 011 golden scenarios.
  *This does not establish* global API budget health — the
  sweep's budget machinery remains the fleet's accounting.

- **FR-019 — Skill and docs currency, and the awareness
  broadcast.**
  *Behavior*: the change that ships each part updates, in
  the same change: the repo SKILL.md and skills pack (the
  power verbs, the downtime record, the ladder, the
  exceptions — written so any agent can request a controlled
  reboot correctly, read a record, and run the duty), the
  dedicated Syncyard skill in the owner's custom-skills
  tree (created under this spec if it still does not exist),
  SECURITY.md's shutdown-and-recovery section (extended to
  initiated actions, in the envelope's words), and the
  example config. **After** the capability is built and
  proven on real test hosts (the test plan's field legs
  green), and not before, the awareness broadcast goes to
  every fleet machine chat, the dashboard chat, and the
  Fleet umbrella chat: what Syncyard now controls, and the
  standing duty — *an agent that detects a down machine
  raises the record; it does not sit on it.* The broadcast
  list is recorded in this spec's tasks file when sent.
  *Acceptance*: gate — the broadcast is a named human-checked
  step in the tasks file, blocked until the field legs pass;
  the skills currency battery (spec 010 T016 pattern) covers
  the new contract text.
  *This does not establish* adopter behavior — the drills
  and the first real incidents are the evidence, as spec 011
  FR-013 states for its own path.

## Test plan (per OS, stated honestly)

- **Linux — live-proven target.** Field legs on real hosts,
  in order: (1) tower-offsite — power reboot with
  boot-back verification, power-off with CONFIRMED-DOWN,
  cancel of a scheduled action, each in a declared window
  with the host's queued work accounted; (2) sbc-inference —
  reboot + return verification (its protection-stack posture
  makes it the honest second); (3) the jammed-host drill —
  a wedged stack on a test host recovered by the ladder's
  lesser step, and a killed-host drill recovered by nobody
  (record → NEEDS-PHYSICAL with the checklist). Payload
  verdicts (the action records) are the evidence; wrapper
  conclusions are transport only.
- **Windows — carried, not live-proven in this spec.** No
  Windows host remains in the fleet (the desktop and laptop
  venues converted to Linux in November 2026). The Windows
  signal bodies are spec 011's already-built routes, held to
  their existing source + golden batteries. If a Windows
  host rejoins the fleet, its first initiated action is a
  drill under this plan before the verb is considered proven
  for it — stated here so the gap is a decision, not a
  discovery.
- **macOS — designed, not built, not proven.** No initiated
  power action, no wake step, no ladder for air-inference
  (FR-016, spec 039 FR-MAC-05). The honest claim for macOS
  in this spec is the exception itself, tested as specified
  in FR-016.
- **Gatekeeper-side batteries** (all platforms): golden +
  spec batteries for Parts A–D in the spec 011 battery
  pattern (`gatekeeper/test_spec042.py`), run in the local
  CI discipline the fleet uses for this repo.

## Owner decisions this spec needs

1. **Spec 011's restart-vs-shutdown re-issue (FR-005-A).**
   The Windows guard, when it vetoes a shutdown it cannot
   classify, re-issues the action as a *restart* — a named
   design decision the spec left for the owner's review, and
   no ratification is on record. With the guard undeployed
   and no Windows host in the fleet, the question is dormant.
   **Recommendation: close it as moot for now**; it reopens
   automatically if a Windows host rejoins or the guard
   deploy (spec 011 T008) is revived.
   **DECISION LOG — RULED 2026-11-17 (owner, Syncyard
   chat): CLOSED AS MOOT**, on the recommendation as
   written. Reopening condition unchanged: a Windows host
   rejoins the fleet, or the guard deploy (spec 011 T008)
   is revived. This closes spec 011's last open design
   question; the guard's build/deploy tasks stay spec
   011's and stay dormant.
2. **Wake-on-LAN enablement.** WoL needs per-host firmware
   posture (BIOS wake enable), a wired NIC path, and a
   LAN-resident sender. laptop-bench's wired NIC lives on
   its Thunderbolt dock and the box roams — it is the wrong
   candidate twice over. **Recommendation: wave 1 configures
   WoL only for fixed, wired hosts where a fleet sender
   shares the LAN (tower-compute, tower-offsite,
   sbc-inference, mini-server as candidates, each proven or
   recorded failed at first attempt); laptop-bench and
   air-inference stay wake-free by design.** The alternative
   — deferring WoL entirely — leaves the ladder's step 2
   empty in wave 1, which the ladder tolerates by design.
   **DECISION LOG — RULED 2026-11-17 (owner, Syncyard
   chat): ADOPTED AS RECOMMENDED.** WoL scope is fixed
   wired hosts only (tower-compute, tower-offsite,
   sbc-inference, mini-server as candidates, each proven or
   recorded failed at first attempt); laptop-bench and
   air-inference stay wake-free by design.
3. **First rollout wave.** **Recommendation: tower-compute,
   tower-offsite, sbc-inference** (fixed Linux hosts with
   live agent channels) for the field legs and first
   production use; **mini-server joins second** — it carries
   the fleet's manager/dashboard stack, so its power actions
   have the widest blast radius and deserve the verbs proven
   elsewhere first. Roaming and off-fleet hosts stay out per
   FR-016 regardless of wave.
   **DECISION LOG — RULED 2026-11-17 (owner, Syncyard
   chat): the first rollout wave INCLUDES mini-server**
   alongside tower-compute, tower-offsite, and
   sbc-inference. The owner overruled the recommendation
   to hold mini-server to a second wave.
4. **Downtime push set.** FR-013 pushes open / escalate /
   close to four chats (Syncyard, umbrella, the machine's
   own chat, main). **Recommendation: keep all four for all
   three transitions** — dedupe bounds an incident to three
   pushes per chat, and the main chat is where the owner
   reads first. The narrower alternative (main chat gets
   escalations only) is named in case alarm volume argues
   otherwise after the first real incidents.
   **DECISION LOG — RULED 2026-11-17 (owner, Syncyard
   chat): the NARROW push set is adopted, overruling the
   four-chat push as drafted.** Pushes go to the MAIN
   CHAT ON ESCALATION ONLY (ladder exhausted /
   NEEDS-PHYSICAL); open and close transitions are
   written to the record but NOT pushed, and the Syncyard
   chat, Fleet umbrella, and machine chats receive no
   downtime pushes. The record itself stays fleet-visible
   in the gatekeeper state (`gk status`, the snapshot).
5. **Defaults ratification.** `power.return_window_s` 900,
   `power.confirm_down_s` 180, `downtime.ladder_budget_s`
   1800, backoff +2/+5/+10 min, slow re-probe 3600.
   **Recommendation: adopt as drafted**; all are config, and
   the first field legs are the evidence to tune them by.
   **DECISION LOG — RULED 2026-11-17 (owner, Syncyard
   chat): ADOPTED AS DRAFTED** (return window 900 s,
   confirm-down 180 s, ladder budget 1800 s, backoff
   +2/+5/+10 min, slow re-probe 3600 s). With this ruling
   the decision queue is complete: all five decisions
   (D1–D5) are ruled.

## Non-goals

- **No prevention**, restated: nothing here vetoes a forced
  shutdown or survives a power loss on the host.
- **No silent anything**: no silent re-dispatch (spec 011),
  no silent power action, no silent ladder step, no silent
  recovery claim.
- **No new trigger surfaces** (spec 010 FR-009 unchanged).
- **No cross-host failover** of interrupted work (spec 010
  non-goal, unchanged).
- **No monitoring product**: the downtime record is a fleet
  operations record inside Syncyard, not a general uptime
  service, and it watches fleet hosts only.
- **No change to the roaming hosts' posture**: this spec
  spends nothing on making air-inference or laptop-bench
  reachable; their exemption is the feature.

## Conflicts with existing specs, named at draft time

- **Spec 011 FR-015 vs this spec's FR-001.** FR-001
  generalizes FR-015's verb; the alias preserves FR-015's
  semantics and its battery. If the two ever disagree, this
  spec's Part A governs initiated actions and FR-015 stands
  as its historical first form.
- **Spec 011 T014 (recovery handshake) vs FR-005.** FR-005's
  interim identity is a deliberate, labeled weakening until
  T014 lands; the spec does not pretend the interim check is
  the handshake, and records carry which standard closed
  them.
- **Spec 040 (draft) vs FR-009 / FR-014 step 4.** The
  stack-restart verb is specified here as a surface; spec
  040 owns what happens inside the host when it fires. If
  spec 040's ratified text names the surface differently,
  the two specs reconcile at 040's landing, with the ladder
  calling whatever surface exists.
- **Spec 039 FR-MAC-05 vs FR-010/FR-016.** No conflict:
  this spec adopts 039's no-WoL-promise and sleeping-Mac
  rules verbatim as its own exception text.

## Success criteria

- An operator can reboot or power off any wave-1 Linux host
  with one command, and the action record — not anyone's
  memory — says what was drained, what was signaled, and
  how the outcome was verified.
- A host that vanishes unplanned produces exactly one
  downtime record, three fleet pushes at most per chat, a
  complete ladder log, and either a verified recovery or a
  NEEDS PHYSICAL PRESENCE state naming its owner and its
  checklist.
- A host that is told to reboot and does not come back is
  *reported* by its own action record at window expiry —
  the fleet never learns about a failed return from silence.
- The roaming hosts' silence produces nothing at all, and
  the first thing any agent in the fleet does on detecting
  a down machine is raise the record — because the skill
  they all read says so, in those words.
