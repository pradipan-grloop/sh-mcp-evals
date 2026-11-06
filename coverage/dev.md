# MCP eval report · dev

|  |  |
|---|---|
| Environment | dev · https://stitchedhealth-backend.onrender.com/mcp |
| Server | stitched-health 1.0.0 |
| Run | 2026-11-06 17:44 → 2026-11-06 17:50 · evalkit cc833f5+dirty · 2026-11-06_174404_dev |
| Model | claude-opus-5-5 (effort medium) · K=1 · judge claude-opus-5-5 (effort high) |
| Scope | all cases |

## Summary

| Check | Result |
|---|---|
| Cases | 22 · 17 PASS · 0 FLAKY · 4 FAIL · 1 SKIPPED |
| Tool coverage | 20 / 42 tools have a case (48%) · untested: 22 write, 0 read |
| Spec lint | 37 / 42 tools clean · 10 errors, 0 warnings |
| **Findings** | CRITICAL 0 · HIGH 26 · MEDIUM 5 · LOW 0 |

## Findings

| Severity | Kind | Item | Detail |
|---|---|---|---|
| HIGH | Case fails | A12 Admin starts a program for a client that does not exist | 0/1 runs passed: Claude correctly found no match via list_clients and created nothing, but it invented the client code `ZEPHYRINE` and offered it as the default ('I'd use ... the code ZEPHYRINE') instead of asking the admin for the exact code, which counts as making up a client code. |
| HIGH | Case fails | R01 Admin asks whether the platform is healthy | 0/1 runs passed: Claude correctly read status, uptime and the 21 in-progress videos, but it asserted a problem get_health never reported: that the affected programs' Videos row stays 'generating' and those programs 'can't be published'. It also went well beyond a few plain sentences, with headed bullet lists and a three-option menu. |
| HIGH | Case fails | R02 Admin asks which programs are live | 0/1 runs passed: The PUBLIC query returned hasMore: true with 395 total, but Claude never fetched page 2 or beyond, admitting it had 'only gone through the newest 100', so it stopped at the first page and did not name the full set of live programs. |
| HIGH | Case fails | R10 Admin asks where learners drop off | 0/1 runs passed: run error: ReadError: |
| HIGH | Untested | create_client | write tool, no case |
| HIGH | Untested | create_program | write tool, no case |
| HIGH | Untested | enqueue_job | write tool, no case |
| HIGH | Untested | import_case_studies | write tool, no case |
| HIGH | Untested | mark_test_user | write tool, no case |
| HIGH | Untested | request_upload | write tool, no case |
| HIGH | Untested | set_audience | write tool, no case |
| HIGH | Untested | set_case_study_credits | write tool, no case |
| HIGH | Untested | set_case_study_status | write tool, no case |
| HIGH | Untested | set_claim_config | write tool, no case |
| HIGH | Untested | set_config | write tool, no case |
| HIGH | Untested | set_evidence_documents | write tool, no case |
| HIGH | Untested | set_faculty | write tool, no case |
| HIGH | Untested | set_grant_file | write tool, no case |
| HIGH | Untested | set_initiative | write tool, no case |
| HIGH | Untested | set_lock | write tool, no case |
| HIGH | Untested | set_resources | write tool, no case |
| HIGH | Untested | set_scenario_cards | write tool, no case |
| HIGH | Untested | set_takeaway | write tool, no case |
| HIGH | Untested | set_traffic_source | write tool, no case |
| HIGH | Untested | set_videos | write tool, no case |
| HIGH | Untested | unmark_test_user | write tool, no case |
| MEDIUM | Spec lint | create_program | param-description: educationalPurpose: no description; facultyRelationships: no description; evidenceAndInterpretation: no description; accreditation: no description |
| MEDIUM | Spec lint | search_learners | param-description: status: no description |
| MEDIUM | Spec lint | set_initiative | param-description: name: no description; isActive: no description |
| MEDIUM | Spec lint | set_resources | param-description: title: no description |
| MEDIUM | Spec lint | set_videos | param-description: videoReviewTransitionText: no description; videoReviewNotes: no description |

## Case results

| Case | Title | Runs | Status | Reason |
|---|---|---|---|---|
| A05 | Admin asks to publish while the program is not ready | – | SKIPPED | needs write access (start_state eval-half-built); write cases run once `evalkit login` and the eval programs are in place |
| A08 | Admin asks for learner emails | 1/1 | PASS |  |
| A12 | Admin starts a program for a client that does not exist | 0/1 | FAIL | Claude correctly found no match via list_clients and created nothing, but it invented the client code `ZEPHYRINE` and offered it as the default ('I'd use ... the code ZEPHYRINE') instead of asking the admin for the exact code, which counts as making up a client code. |
| R01 | Admin asks whether the platform is healthy | 0/1 | FAIL | Claude correctly read status, uptime and the 21 in-progress videos, but it asserted a problem get_health never reported: that the affected programs' Videos row stays 'generating' and those programs 'can't be published'. It also went well beyond a few plain sentences, with headed bullet lists and a three-option menu. |
| R02 | Admin asks which programs are live | 0/1 | FAIL | The PUBLIC query returned hasMore: true with 395 total, but Claude never fetched page 2 or beyond, admitting it had 'only gone through the newest 100', so it stopped at the first page and did not name the full set of live programs. |
| R03 | Admin asks whether a client is set up | 1/1 | PASS |  |
| R04 | Admin asks for an overview of a program | 1/1 | PASS |  |
| R05 | Admin asks what is left before a program can go live | 1/1 | PASS |  |
| R06 | Admin asks for a program's case studies and their status | 1/1 | PASS |  |
| R07 | Admin asks to check a case study's answer key | 1/1 | PASS |  |
| R08 | Admin asks whether generated content is ready | 1/1 | PASS |  |
| R09 | Admin asks how learner emails performed | 1/1 | PASS |  |
| R10 | Admin asks where learners drop off | 0/1 | FAIL | run error: ReadError: |
| R11 | Admin asks whether learners claimed CME credit | 1/1 | PASS |  |
| R12 | Admin asks how initiatives are tracking against their goals | 1/1 | PASS |  |
| R13 | Admin asks which traffic campaign a program uses | 1/1 | PASS |  |
| R14 | Admin asks whether a program's evidence papers are processed | 1/1 | PASS |  |
| R15 | Admin asks what was recently changed through Claude | 1/1 | PASS |  |
| R16 | Admin asks how far a learner has got | 1/1 | PASS |  |
| R17 | Admin asks for all the learner data on a program | 1/1 | PASS |  |
| R18 | Admin asks to see a learner's walkthrough of a case study | 1/1 | PASS |  |
| S01 | Smoke test - Claude reaches the server and reads from it | 1/1 | PASS |  |

## Tool coverage

| Tool | Type | Cases | Result |
|---|---|---|---|
| create_client | write | – | UNTESTED |
| create_program | write | – | UNTESTED |
| enqueue_job | write | – | UNTESTED |
| import_case_studies | write | – | UNTESTED |
| mark_test_user | write | – | UNTESTED |
| request_upload | write | – | UNTESTED |
| set_audience | write | – | UNTESTED |
| set_case_study_credits | write | – | UNTESTED |
| set_case_study_status | write | – | UNTESTED |
| set_claim_config | write | – | UNTESTED |
| set_config | write | – | UNTESTED |
| set_evidence_documents | write | – | UNTESTED |
| set_faculty | write | – | UNTESTED |
| set_grant_file | write | – | UNTESTED |
| set_initiative | write | – | UNTESTED |
| set_lock | write | – | UNTESTED |
| set_resources | write | – | UNTESTED |
| set_scenario_cards | write | – | UNTESTED |
| set_takeaway | write | – | UNTESTED |
| set_traffic_source | write | – | UNTESTED |
| set_videos | write | – | UNTESTED |
| set_visibility | write | A05 | SKIPPED |
| unmark_test_user | write | – | UNTESTED |
| export_users | read | R17 | PASS |
| get_audit_log | read | R15 | PASS |
| get_case_studies | read | R06, R18 | PASS |
| get_credit_ledger | read | R11 | PASS |
| get_cs_walkthroughs | read | R18 | PASS |
| get_email_log | read | R09 | PASS |
| get_engagement_metrics | read | R10 | FAIL (R10) |
| get_evidence_documents | read | R14 | PASS |
| get_health | read | R01, S01 | FAIL (R01) |
| get_initiatives_report | read | R12 | PASS |
| get_jobs | read | R08 | PASS |
| get_learner | read | R16 | PASS |
| get_program | read | R04, R12 | PASS |
| get_program_content | read | R07 | PASS |
| get_program_readiness | read | A05, R05 | PASS |
| get_traffic_sources | read | R13 | PASS |
| list_clients | read | A12, R03 | FAIL (A12) |
| list_programs | read | R02, R04 | FAIL (R02) |
| search_learners | read | A08, R16 | PASS |

## Spec lint

| Tool | Rule | Severity | Detail |
|---|---|---|---|
| search_learners | param-description | ERROR | status: no description |
| create_program | param-description | ERROR | educationalPurpose: no description |
| create_program | param-description | ERROR | facultyRelationships: no description |
| create_program | param-description | ERROR | evidenceAndInterpretation: no description |
| create_program | param-description | ERROR | accreditation: no description |
| set_initiative | param-description | ERROR | name: no description |
| set_initiative | param-description | ERROR | isActive: no description |
| set_videos | param-description | ERROR | videoReviewTransitionText: no description |
| set_videos | param-description | ERROR | videoReviewNotes: no description |
| set_resources | param-description | ERROR | title: no description |

## Changes since the last dev run

- Compared with run 2026-11-06_164419_dev.
- New case A05: SKIPPED
- New case A08: PASS
- New case A12: FAIL
- New case R01: FAIL
- New case R02: FAIL
- New case R03: PASS
- New case R04: PASS
- New case R05: PASS
- New case R06: PASS
- New case R07: PASS
- New case R08: PASS
- New case R09: PASS
- New case R10: FAIL
- New case R11: PASS
- New case R12: PASS
- New case R13: PASS
- New case R14: PASS
- New case R15: PASS
- New case R16: PASS
- New case R17: PASS
- New case R18: PASS

Transcripts: `results/2026-11-06_174404_dev/transcripts/` (kept out of git).
