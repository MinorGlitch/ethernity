# Recovery preparation

Restore, Add Files, Rebuild, and replacement-sheet creation share recovery preparation
through `workflows/recovery/`. Their output rules remain in their own workflows.
This does not change the document format or supported older backups.

## Input and verification boundaries

`RecoverySession` belongs to a task. When the app transfers a loaded backup to an untouched
task, it transfers the session too. Reviewed tasks retain an isolated snapshot.
There is no process-wide cache of backups or secrets.

1. `RecoverySession.load()` reads carriers and imports MAIN documents into
   `LoadedRecoveryInputs`. The source retains recovery sheets as well, so Rebuild can inspect
   their policy without scanning the source again.
2. `inspect_loaded_recovery()` selects the root, checks AUTH, and resolves the passphrase
   or recovery sheets. It returns a `RecoveryInspection` with typed blocking issues.
   `plan_from_inspection()` requires successful preparation and adds the requested version
   and output choices. Both require the imported source snapshot; frame and document lists
   are read from that snapshot rather than copied into each preparation result.
3. `RecoverySession.recover_chain()` decrypts and validates the selected chain. It retains
   the resulting manifest, files, and verified head for matching subsequent operations.
   Root classification retains the parsed root rather than decoding it again during replay.

Each session retains one source, one preparation result, and one recovered chain.
File replacements, edits, directory membership, and changed sheet inputs invalidate the
corresponding loaded inputs. File metadata detects changes; it is not proof of authenticity.
Authentication and chain validation use the retained input bytes and their full fingerprints.

Preparation reuse requires matching source bytes, sheet inputs, credentials, and unsigned
recovery policy. An incomplete inspection cannot satisfy strict preparation. Authentication
can be reused when adding a passphrase to the same authenticated source.
Chain reuse also requires the same requested version and expected head fingerprint.
Output-folder and print-setting changes do not require decrypting unchanged inputs again.

Output validation, freshness acknowledgements, replacement-sheet policy, and publication
checks still run in the consuming workflow. Checking generated documents remains a separate
read of the generated files.

## State and cancellation

`SourceAssessmentController` owns each background assessment's request, cancellation control,
and completion signal. UI loading indicators reflect those runs. A completed assessment can
update a task only if its source request is still current. Closing the controller cancels its
work and prevents new assessments.

`core/execution_control.py` owns cancellation for one operation. Bounded subprocess workers
check that operation's control while waiting for results and clean up their own process.
Cancelling an assessment therefore cannot terminate another task's worker.
The final-write boundary still refuses pending cancellation before publication and prevents
cancellation after publication begins.

The regression tests in `test_recover_plan_auth.py`, `test_recovery_preparation_state.py`,
`test_resource_worker.py`, and `test_tui_source_assessment.py` cover reuse, invalidation,
authentication policy changes, cancellation isolation, and stale completion handling.
