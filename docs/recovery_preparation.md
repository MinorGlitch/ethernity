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
read of the generated files. Each check owns a fresh session and retains it across the
passphrase prompt. Its execution plan uses that same inspection. All supplied recovery sheets
must pass validation before the check reconstructs the passphrase using only the minimum
root-bound quorum. Temporary plaintext is removed on success, failure, or cancellation.

Rebuild classifies unique sheet carriers once. Its policy calculation reuses parsed and verified
sheets from strict preparation when the complete set and trusted identity match. Root policy
still requires a quorum; selected-update policy can use authenticated metadata from fewer
sheets. Unsigned preparation cannot supply a reusable signature result.

Restore preflight and the directory writer use the same new-or-empty destination rule. The
writer checks again at execution. The shared Restore task used by the app and `run restore`
requests directory output explicitly, including for a single recovered file. Low-level recovery
requests retain their file-or-directory behavior. Review screens display the task's write policy
instead of inferring overwrite behavior from whether a path exists.

Add Files retains typed chain state, the selected input, and blocking issues for publication.
It does not build a second inspection summary. After a verified update is published, optional
recovery sheets use the root credentials retained during preparation and the published update's
fingerprint. They do not import or decrypt the source again. Standalone replacement operations
still prepare and verify their inputs before calling the same sheet generator. That generator
enforces output quorums, signing-key binding, and compatible replacement rules for both callers.

The document inspector's automatic text parser returns both the detected format and decoded
frames, so valid QR payloads are decoded once. Explicit format selection uses the same parsers.

## State and cancellation

`SourceAssessmentController` owns each background assessment's request, cancellation control,
and completion signal. UI loading indicators reflect those runs. A completed assessment can
update a task only if its source request is still current. Closing the controller cancels its
work and prevents new assessments. Generated-document checks are owned by their result
screen; dismissing that screen cancels the check. Print estimates cancel obsolete work when
inputs change or are explicitly reselected, then process the latest request. Both controllers
use the existing operation control and keep work off the UI thread.

A synchronous UI refresh captures each task's source request once. Validation, summaries,
navigation, and the workflow presenter use that request until the refresh ends. The scope is
cleared even if rendering fails; the next refresh checks file metadata and configuration again.
Background assessment completion and execution do not rely on a presentation snapshot.

`core/execution_control.py` owns cancellation for one operation. Bounded subprocess workers
check that operation's control while waiting for results and clean up their own process.
Cancelling an assessment therefore cannot terminate another task's worker.
The final-write boundary still refuses pending cancellation before publication and prevents
cancellation after publication begins.

The regression tests in `test_recover_plan_auth.py`, `test_recovery_preparation_state.py`,
`test_resource_worker.py`, and `test_tui_source_assessment.py` cover reuse, invalidation,
authentication policy changes, cancellation isolation, and stale completion handling.

## Browser collection

Collection retains successful signature checks for unchanged AUTH and sheet payloads. The
comparison includes the complete signed message, signature, and public key, with private byte
snapshots kept under weak references. Cloned collection drafts can reuse those checks; changing
any signed field requires verification again. Conflicts and document binding are still checked,
failed signatures are not retained, and final recovery performs its own verification. Resetting
the collection releases its payloads and their retained checks.
