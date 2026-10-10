# AabFlow complete work DAG

Generated from [agent-dag.json](agent-dag.json); regenerate with `python scripts/agent_dag.py document` inside Docker.
Read [AGENT_WORKFLOW.md](AGENT_WORKFLOW.md) for execution, ownership, isolated runtimes, checkpoints and reviewer gates.
This graph is a plan, not evidence of executed product work.

```mermaid
flowchart TD
  P00["P00: Merged foundation snapshot"]
  P01["P01: Exact libraries and GPU evaluation snapshot"]
  P00 --> P01
  G_CONTRACT["G-CONTRACT: Inventory and freeze shared interfaces"]
  P00 --> G_CONTRACT
  P02["P02: Real pilot provenance and reproduction"]
  G_CONTRACT --> P02
  P03["P03: Decision invariants and acceptance runner"]
  G_CONTRACT --> P03
  P01 --> P03
  P05_api["P05-api: Reports jobs and retrieval contract"]
  G_CONTRACT --> P05_api
  P04["P04: Analysis, surrogate and preview performance"]
  G_CONTRACT --> P04
  P01 --> P04
  P03 --> P04
  P05_files["P05-files: Self-contained action report and evidence files"]
  P05_api --> P05_files
  P03 --> P05_files
  P06_service["P06-service: Canonical SDG proxies and distribution"]
  G_CONTRACT --> P06_service
  P03 --> P06_service
  P04 --> P06_service
  P06_ui["P06-ui: Impact cards in real screen"]
  P06_service --> P06_ui
  P07_process["P07-process: Real raw intake and process jobs"]
  G_CONTRACT --> P07_process
  P02 --> P07_process
  P07_review["P07-review: Versioned review and immutable publish"]
  P07_process --> P07_review
  P01 --> P07_review
  P07_ui["P07-ui: Onboarding wizard end to end"]
  P07_review --> P07_ui
  P08_zip["P08-zip: Finished-package export/import validation"]
  P05_files --> P08_zip
  P07_review --> P08_zip
  P08_pack["P08-pack: Reproducible evidence pack assembly"]
  P08_zip --> P08_pack
  P04 --> P08_pack
  P06_ui --> P08_pack
  P07_ui --> P08_pack
  P11_core["P11-core: Non-chat UI and report consistency"]
  P05_files --> P11_core
  P06_ui --> P11_core
  P07_ui --> P11_core
  P04 --> P11_core
  P09_offline["P09-offline: Network-denied complete core"]
  P08_pack --> P09_offline
  P11_core --> P09_offline
  P09_restart["P09-restart: Restart, interruption and tamper recovery"]
  P09_offline --> P09_restart
  G_CORE["G-CORE: Complete non-chat acceptance gate"]
  P01 --> G_CORE
  P02 --> G_CORE
  P03 --> G_CORE
  P04 --> G_CORE
  P05_files --> G_CORE
  P06_ui --> G_CORE
  P07_ui --> G_CORE
  P08_pack --> G_CORE
  P09_restart --> G_CORE
  P11_core --> G_CORE
  G_CONNECT["G-CONNECT: Provider connectivity preparation only"]
  G_CONTRACT --> G_CONNECT
  P10["P10: Copilot wiring without the 90-run evaluation"]
  G_CORE --> P10
  G_CONNECT --> P10
  P11_final["P11-final: Full three-surface consistency and six-screen UI gate"]
  P11_core --> P11_final
  P10 --> P11_final
  P12["P12: Actual five-minute stage route E2E"]
  P11_final --> P12
  P08_pack --> P12
  P09_restart --> P12
  P13_timing["P13-timing: Presentation-device cold launch and timings"]
  P12 --> P13_timing
  G_REVIEW["G-REVIEW: Reviewer-merged prerequisite gate"]
  P00 --> G_REVIEW
  P01 --> G_REVIEW
  P02 --> G_REVIEW
  P03 --> G_REVIEW
  P04 --> G_REVIEW
  P05_files --> G_REVIEW
  P06_ui --> G_REVIEW
  P07_ui --> G_REVIEW
  P08_pack --> G_REVIEW
  P09_restart --> G_REVIEW
  P10 --> G_REVIEW
  P11_final --> G_REVIEW
  P12 --> G_REVIEW
  P13_release["P13-release: Complete release report and final proof pack"]
  P13_timing --> P13_release
  G_REVIEW --> P13_release
  G_RELEASE["G-RELEASE: Independent final release confirmation"]
  P13_release --> G_RELEASE
```

| Node | Owner | Prerequisites | Exclusive resources |
|---|---|---|---|
| P00 | lead | — | — |
| P01 | science | P00 | — |
| G-CONTRACT | lead | P00 | contracts |
| P02 | data | G-CONTRACT | science |
| P03 | api | G-CONTRACT, P01 | science |
| P05-api | api | G-CONTRACT | — |
| P04 | science | G-CONTRACT, P01, P03 | science, gpu |
| P05-files | api | P05-api, P03 | — |
| P06-service | api | G-CONTRACT, P03, P04 | — |
| P06-ui | ui | P06-service | — |
| P07-process | data | G-CONTRACT, P02 | science, gpu |
| P07-review | data | P07-process, P01 | science |
| P07-ui | ui | P07-review | demo |
| P08-zip | api | P05-files, P07-review | — |
| P08-pack | api | P08-zip, P04, P06-ui, P07-ui | — |
| P11-core | ui | P05-files, P06-ui, P07-ui, P04 | demo |
| P09-offline | api | P08-pack, P11-core | demo, science |
| P09-restart | api | P09-offline | demo, science |
| G-CORE | verifier | P01, P02, P03, P04, P05-files, P06-ui, P07-ui, P08-pack, P09-restart, P11-core | demo, science |
| G-CONNECT | lead | G-CONTRACT | provider |
| P10 | api | G-CORE, G-CONNECT | provider |
| P11-final | ui | P11-core, P10 | demo, provider |
| P12 | ui | P11-final, P08-pack, P09-restart | demo, provider, science |
| P13-timing | verifier | P12 | demo, science, provider |
| G-REVIEW | lead | P00, P01, P02, P03, P04, P05-files, P06-ui, P07-ui, P08-pack, P09-restart, P10, P11-final, P12 | — |
| P13-release | lead | P13-timing, G-REVIEW | demo, science, provider |
| G-RELEASE | lead | P13-release | demo, science, provider |

Forecast waves below assume existing prerequisites and future reviews succeed; they are not dispatch permission or time estimates. Runtime `plan --state` uses actual checkpoint/lease records. Bases must contain all prerequisite SHAs.

1. G-CONTRACT
2. P02, P05-api, G-CONNECT
3. P03
4. P04, P05-files
5. P06-service, P07-process
6. P06-ui, P07-review
7. P07-ui, P08-zip
8. P08-pack, P11-core
9. P09-offline
10. P09-restart
11. G-CORE
12. P10
13. P11-final
14. P12
15. P13-timing, G-REVIEW
16. P13-release
17. G-RELEASE

All split nodes retain their parent PNN completion barrier. P11-core is partial AT13/AT14; G-CORE unlocks P10; P11-final completes both ATs. G-REVIEW and G-RELEASE require actual independent reviewer merges/evidence.
