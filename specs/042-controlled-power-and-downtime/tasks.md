# Tasks: Spec 042 — Controlled Power and Fleet Downtime

Sequenced so nothing can act on a host before the record
that accounts for it exists: the action record and the
extended power verb land first (Linux routes, where the
fleet actually lives), boot-back verification second, the
downtime record third, the ladder fourth, and the fleet
awareness broadcast LAST — gated on the field legs, per the
owner's order ("once done and tested, all agents are
aware"). The fleet's standing disciplines bind throughout:
payload verdict over wrapper verdict, pause-first for any
live-component change, verified writes, SKILL.md / skill
currency in the same change as behavior (FR-019), and the
rails of FR-017/FR-018.

## Phase 0 — Owner decisions (gate, before build)
- [x] D1 Spec 011 FR-005-A restart-vs-shutdown re-issue:
      **RULED by the owner 2026-11-17: CLOSED AS MOOT.**
      Reopens automatically if a Windows host rejoins the
      fleet or the Windows shutdown guard (spec 011 T008)
      is deployed. Recorded in spec.md's decision log.
- [x] D2 Wake-on-LAN scope: **RULED by the owner
      2026-11-17: FIXED WIRED HOSTS ONLY** (tower-compute,
      tower-offsite, sbc-inference, mini-server as
      candidates, each proven or recorded failed at first
      attempt); laptop-bench and air-inference stay
      wake-free by design. Recorded in spec.md's decision
      log.
- [x] D3 First rollout wave: **RULED by the owner
      2026-11-17: the first wave INCLUDES mini-server**
      alongside tower-compute, tower-offsite, and
      sbc-inference (the owner overruled the recommendation
      to hold mini-server to a second wave). Recorded in
      spec.md's decision log. (T020's premise changes with
      this ruling: mini-server is a wave-1 host, not a
      second-wave join.)
- [x] D4 Downtime push set: **RULED by the owner
      2026-11-17: the NARROW set** — pushes go to the main
      chat on escalation only (NEEDS-PHYSICAL); open and
      close are record-only, and the Syncyard chat, Fleet
      umbrella, and machine chats receive no downtime
      pushes. This overrules FR-013's four-chat push as
      drafted; recorded in spec.md's decision log.
      (T011's scope narrows with it: one escalation
      registration, one push per escalation.)
- [x] D5 Defaults ratification: **RULED by the owner
      2026-11-17: ADOPTED AS DRAFTED** (return window
      900 s, confirm-down 180 s, ladder budget 1800 s,
      backoff +2/+5/+10 min, slow re-probe 3600 s).
      Recorded in spec.md's decision log. The decision
      queue is now complete (D1–D5 all ruled).

## Phase 1 — The power verb family (FR-001–FR-004, FR-007)
- [x] T001 `gk power --host --action reboot|poweroff|cancel`
      generalizing `gk reboot`: per-OS signal bodies (Linux
      systemctl via backchannel agent shell + linux.yml
      maintenance dispatch; Windows bodies carried from spec
      011 unchanged), route proof exactly as `_reboot_route`,
      `gk reboot` preserved as a byte-identical alias.
      Batteries: route selection, per-OS bodies, unreachable.
      DONE 2026-11-17 (slice 1, test_spec042). Note: route
      proof is exactly _reboot_route as required, whose
      backchannel proof covers heartbeat (wsl2-chain) hosts
      only — so Linux signals today ride the linux.yml
      maintenance dispatch; the Linux backchannel body
      (systemctl / shutdown) is built and would ride the
      backchannel verbatim if route proof ever selects it
      for a Linux host.
- [x] T002 Power-off discipline: `--confirm <host>` required,
      DOWN-BY-ACTION expected state set before signal,
      CONFIRMED-DOWN verdict over `power.confirm_down_s`.
      Battery pins refusal-without-confirm and the ordering.
      DONE 2026-11-17 (slice 1): the battery pins
      refusal-without-confirm, DOWN-BY-ACTION + going-down
      recorded before the signal seam runs, and
      CONFIRMED-DOWN over the full 180 s silence.
- [x] T003 Drain integration: active-job accounting identical
      to `gk reboot`'s; drain-then-signal through spec 011's
      machinery (hold files, drain hold, per-lane window,
      per-job verdicts carried into the action record);
      `remote-poweroff` joins the going-down trigger
      vocabulary. Golden scenarios reused where they pin the
      shared halves.
      DONE 2026-11-17 (slice 1): _drain_host extracted from
      cmd_drain with zero behavior change (test_spec011 +
      test_golden green), invoked by the power verb under
      --drain; remote-poweroff in GOING_DOWN_TRIGGERS.
- [x] T004 Override path: `--force` requires
      `--override-reason` + `--requested-by`; all three
      ledgered and recorded; accounting never skipped.
      Battery pins both refusals and the recorded form.
      DONE 2026-11-17 (slice 1), battery-pinned.
- [x] T005 Cancel: scheduled-action withdrawal; in-grace OS
      abort (Windows `shutdown /a`, Linux `shutdown -c`);
      NOT-CANCELLABLE stated where no abort handle exists;
      verdict from observed host state, never the abort's
      exit code.
      DONE 2026-11-17 (slice 1), battery-pinned incl.
      CANCEL-FAILED from observed state.
- [x] T006 Action records + ledger events (FR-007's full
      vocabulary); an unclosed record renders as an ISSUES
      entry on `gk status`. Config: `power.return_window_s`,
      `power.confirm_down_s`, fail-closed validated, mirrored
      in the example config and the config battery.
      DONE 2026-11-17 (slice 1): records beside the queue
      (power-actions/), FR-007's event vocabulary, unclosed
      record = ISSUES entry, config validated fail-closed +
      example mirrored; the config checks live in
      test_spec042 (the battery this spec's notes name).

## Phase 2 — Boot-back verification + power status (FR-005, FR-008)
- [x] T007 Expected-return tracking: window opens at signal;
      VERIFIED on served identity (fresh heartbeat naming
      the host + liveness record updated; handshake-matched
      once spec 011 T014 exists — records state which
      standard closed them); VERIFIED-LATE amendment;
      RETURN-MISSED at expiry, opening the Part C record with
      the action as detector.
      DONE as machinery 2026-11-17 (slice 1): window at
      signal, VERIFIED only after observed silence + fresh
      identity evidence (interim standard, named in the
      record), VERIFIED-LATE, RETURN-MISSED opening the
      Part C record. Field proof is Phase 6.
- [x] T008 Power section on the host liveness record
      (`power_state`, `last_action`, `last_seen_alive`,
      `expected_return_by`), rendered in `gk status` and the
      fleet-status snapshot; a planned-down host and a
      crashed host never render identically. Batteries pin
      each state.
      DONE 2026-11-17 (slice 1): power section on the
      liveness record, rendered in gk status host lines and
      the snapshot (hosts_power, present only for hosts
      carrying one); battery pins DOWN-BY-ACTION rendering
      vs plain DOWN. last_seen_alive rides the snapshot
      entry from the liveness record.

## Phase 3 — The downtime record (FR-011–FR-013)
- [x] T009 Record store + state machine: one record per
      (host, incident), detectors (sweep liveness transition,
      FR-005 missed return, unreturned going-down, hand
      filing via `gk downtime`), evidence append without
      re-notification, close exactly once.
      DONE 2026-11-17 (slice 1): store + state machine,
      dedupe, evidence append without re-notification,
      close exactly once; detectors wired: sweep liveness
      transition, FR-005 missed return, hand filing. The
      unreturned-going-down detector concludes through the
      same sweep transition (the going-down record is its
      class evidence).
- [x] T010 Class assignment from evidence only (ORDERLY /
      BY-ACTION / NETWORK / UNKNOWN with evidence lines);
      jobs-affected accounting from the gatekeeper's own
      records at detection.
      DONE 2026-11-17 (slice 1), battery-pinned.
- [x] T011 Standing downtime notify registrations (per-host
      chat map in config → Syncyard chat, Fleet umbrella,
      the machine's chat, main chat); one push per target per
      transition (open / NEEDS-PHYSICAL / close); push body
      fields per FR-013. This is the general owning-chat route
      spec 011 Phase 1 named as missing; spec 011's
      going-down pushes keep their existing per-job targets.
      DONE 2026-11-17 as narrowed by ruling D4: the standing
      registration is downtime.escalation_chats (the main
      chat); open/close push nothing; the NEEDS-PHYSICAL
      flip pushes exactly once per target with FR-013's
      body fields, rendered by the existing outbox.

## Phase 4 — Stack restart + wake (FR-009, FR-010)
- [ ] T012 `gk host-restart --host`: stack-only restart over
      any host-proving live route; per-component verdicts
      (agent, each runner lane) from the stack's own answers
      afterward. Surface only — spec 040 owns the internals
      it triggers; reconcile naming at spec 040's landing.
- [ ] T013 WoL: `wol` config block (mac, via, enabled),
      fail-closed validation; the send executed by the `via`
      host, logged with sender/target/time; host record
      distinguishes CONFIGURED from PROVEN (first observed
      wake) and records a failed first attempt as FAILED,
      never silently retried as if unconfigured.

## Phase 5 — The recovery ladder + physical escalation (FR-014–FR-016)
- [ ] T014 Ladder engine: steps 1–5 in order, each bounded
      and logged to the record (multi-channel re-probe; wake
      where configured; +2/+5/+10 backoff re-probes; lesser
      stack restart over a proven-live channel; ONE
      controlled reboot over a proven-live route, drain
      accounting included); budget `downtime.ladder_budget_s`;
      closing states RECOVERED-BY-LADDER (step named) /
      RECOVERED-UNASSISTED / still-down. Recovery claimed
      only on the host's own identity (FR-005 standard).
- [ ] T015 NEEDS-PHYSICAL flip: named owner per host
      (Tristen; Ryan Anderson for a hand-filed
      layer1labs-inference record), per-class on-site
      checklist (incl. laptop-bench's dock note, for the
      hand-filed case), ladder log attached as already-tried;
      slow re-probe only afterward, with close-on-return.
- [x] T016 Exceptions enforced in code, not config habit:
      `roaming: true` hosts (air-inference, laptop-bench)
      produce zero records/pushes/ladder steps at any silence
      length (72 h fixture); layer1labs-inference: no ladder,
      no power verbs, hand-filed records only with the
      limited re-probe ladder.
      PARTIAL 2026-11-17 (slice 1): the record/push half is
      enforced in code and battery-pinned (roaming hosts
      open zero records under any detector; the
      layer1labs-inference shape = off_fleet: hand-filed
      only, no power verbs). The ladder half lands with
      T014 (slice 2); the 72 h fixture is Phase 6 drill
      work.

## Phase 6 — Field legs (gate for FR-019's broadcast)
- [ ] T017 tower-offsite leg (declared window): reboot +
      VERIFIED return; poweroff + CONFIRMED-DOWN; scheduled
      action + cancel confirmed. Action records are the
      evidence.
- [ ] T018 sbc-inference leg: reboot + VERIFIED return.
- [ ] T019 Drills: jammed-stack fixture recovered by the
      ladder's lesser step; killed-host fixture walked to
      NEEDS-PHYSICAL with checklist; roaming fixture silent
      for the full drill window. Results recorded here.
- [ ] T020 mini-server joins (second wave, per D3): one
      reboot leg in a declared window after T017–T019 pass.

## Phase 7 — Currency + awareness (FR-019)
- [ ] T021 SKILL.md + skills pack: power verbs, downtime
      record, ladder, exceptions, the detector duty; the
      dedicated Syncyard skill in ~/workspace/custom-skills/
      created or updated to the same contract; SECURITY.md
      initiated-actions section; example config complete.
      Currency battery covers the new text.
- [ ] T022 Awareness broadcast — ONLY after T017–T019 pass:
      to every fleet machine chat (tower-compute,
      tower-offsite, mini-server, sbc-inference,
      air-inference, laptop-bench, layer1labs-inference),
      the Wazuh/dashboard chat, and the Fleet umbrella chat.
      Broadcast list + date recorded here when sent.
- [ ] T023 CHANGELOG + version decision with the owner.

## Notes for the implementing phases
- Spec 011's batteries (`gatekeeper/test_spec011.py`,
  `test_golden.py` scenario 6/7) are the pattern and, where
  the halves are shared, the actual fixtures — extend, do
  not fork. New battery: `gatekeeper/test_spec042.py`.
- The going-down record format does not change. The only
  vocabulary addition is the `remote-poweroff` trigger,
  which rides spec 011's ingest extension path (the same
  way `remote-reboot` joined it in T021).
- Nothing in any phase dispatches through a new surface:
  the dispatch-only invariant (spec 010 FR-009) binds every
  task above, and every power signal rides the backchannel
  or a maintenance dispatch that already exists.
