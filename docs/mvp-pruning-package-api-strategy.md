# Package API Break Strategy

Decision record for `bd-27n.5.4`.

This note isolates the `src/notebooklm/__init__.py` decision from the broader
CLI/SDK pruning work. The goal is to stop internal module pruning from turning
into an accidental package-root API contraction.

## What The Repo Currently Promises

- `src/notebooklm/__init__.py` exports the public package surface through
  `__all__`.
- `docs/stability.md` says the public API is the contents of `__all__` and that
  public API breaking changes require a major version bump.
- `pyproject.toml` still publishes version `0.3.3`.
- The repo itself still uses root imports in tests, docs, and examples for
  client entry points, exceptions, enums, and deferred-compatibility types.

Taken together, that means `src/notebooklm/__init__.py` is not just a convenience
barrel. It is an explicit compatibility boundary.

## Export Inventory By Bucket

The exact symbol list remains in `src/notebooklm/__init__.py`. For pruning
purposes, the exports fall into four buckets.

### 1. Reduced-MVP Root Exports

These still belong in the reduced MVP and should remain easy to import from the
package root:

- client/auth entry points:
  `NotebookLMClient`, `AuthTokens`, `DEFAULT_STORAGE_PATH`
- core retained data/results:
  `Notebook`, `NotebookDescription`, `SuggestedTopic`, `Source`, `Artifact`,
  `GenerationStatus`, `AskResult`, `ChatReference`
- retained MVP enums:
  `SourceType`, `ArtifactType`, `AudioFormat`, `AudioLength`, `ReportFormat`,
  `ChatGoal`, `ChatResponseLength`, `DriveMimeType`, `SourceStatus`
- core error surface:
  `NotebookLMError`, `ValidationError`, `ConfigurationError`, `RPCError`,
  `DecodingError`, `UnknownRPCMethodError`, `AuthError`, `NetworkError`,
  `RPCTimeoutError`, `RateLimitError`, `ServerError`, `ClientError`,
  `NotebookError`, `NotebookNotFoundError`, `ChatError`, `SourceError`,
  `SourceAddError`, `SourceProcessingError`, `SourceTimeoutError`,
  `SourceNotFoundError`, `ArtifactError`, `ArtifactNotFoundError`,
  `ArtifactNotReadyError`, `ArtifactParseError`

### 2. Deferred-Compatibility Root Exports

These do not really belong to the reduced MVP anymore, but removing them from
the package root on this branch would be a public API break:

- deferred notes/settings/sharing stock:
  `Note`, `ChatSettings`, `UNSET`, `SharedUser`, `ShareStatus`,
  `ShareAccess`, `ShareViewLevel`, `SharePermission`
- parity/history/fulltext stock:
  `ConversationTurn`, `SourceFulltext`, `ChatSettingsParseError`,
  `ChatSettingsValidationError`, `ChatSettingsUpdateError`
- older non-core helper/result types:
  `ReportSuggestion`, `ArtifactDownloadError`, `ExportType`

### 3. Non-MVP Media/Formatting Enums Still Public

These are tied to flows the pruning work has removed from the active MVP story,
but they are still package-root exports today:

- `VideoFormat`, `VideoStyle`
- `QuizQuantity`, `QuizDifficulty`
- `InfographicOrientation`, `InfographicDetail`
- `SlideDeckFormat`, `SlideDeckLength`

### 4. Already-Deprecated Root Export

- `StudioContentType`

This one already uses a deprecation shim in `__getattr__`. It should stay
handled as explicit compatibility debt, not as justification to silently remove
more root exports during MVP pruning.

## Decision

Keep `src/notebooklm/__init__.py` functionally unchanged on the current MVP
pruning branch.

That means:

- do not remove root exports as part of internal module cleanup
- do not treat the disappearance of CLI commands or internal helpers as
  permission to contract `__all__`
- do not use default-test trimming as the sole proof that a package-root export
  is safe to remove

The branch should keep the root package as a compatibility shim while the
internal MVP boundary settles.

## Allowed Near-Term Changes

- documentation that clarifies which exports are core MVP versus compatibility
  holdovers
- comments in `src/notebooklm/__init__.py` that warn contributors not to prune
  the package root casually
- deprecation warnings or migration guidance that preserve runtime compatibility

## Not Allowed In Routine Pruning Beads

- silent removal of deferred notes/settings/sharing exports from the root
- silent removal of non-MVP enums or exceptions just because their primary CLI
  surface is gone
- mixing a package-root API break into unrelated internal cleanup beads

## Release Strategy For Future Contraction

Recommended path:

1. Keep `src/notebooklm/__init__.py` intact through the current pruning stream.
2. Open a dedicated package-API break bead or branch once the desired post-prune
   root export set is stable.
3. Add deprecation/migration guidance for any root exports that will disappear.
4. Update `docs/stability.md`, `docs/python-api.md`, release notes, and the
   migration guide in the same lane.
5. Ship the contraction only with an explicit release-policy decision.

Under the current published stability policy, that release-policy decision is a
major-version event, not an incidental `0.3.x` pruning change.

## Known Policy Tension To Resolve Later

`docs/stability.md` says public API breaks require a major version bump, but it
also still says `StudioContentType` will be removed in `v0.4.0`. That older
deprecation note should be reconciled in a dedicated release-policy follow-up,
not silently expanded into a larger `__init__.py` contraction during this MVP
pruning branch.

## Practical Outcome For Follow-Up Beads

- `bd-27n.5.4` resolves to an intentional deferral decision, not to an export
  removal.
- Future pruning beads may keep shrinking internal modules while leaving the
  package root broad.
- Any future `src/notebooklm/__init__.py` contraction must be tracked as its own
  compatibility/release task with migration notes and an explicit versioning
  call.
