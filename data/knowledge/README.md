# Knowledge packs

Versioned, source-attributed architectural knowledge for BuildAI 3D (Phase 3.5). The full
design is in [docs/knowledge.md](../../docs/knowledge.md). Code: `apps/api/app/modules/catalog`.

```
sources/<id>.yaml              one record per source (bibliography, fingerprint, usage policy)
packs/<id>.v<n>/pack.yaml      pack manifest; lists every file of the pack
regions/<id>.v<n>.yaml         region profiles (compose rules + drawing profile + packs)
knowledge.lock.json            SHA-256 of every source, pack and region
```

Rules for authors:

1. **Knowledge is not rules.** Nothing here constrains a design. Enforceable minimums and
   maximums live only in `data/rules-profiles/`.
2. **Every object has provenance** (`source`, printed `pages`, `section`, `figures`/`tables`)
   and a `status`. Source-derived knowledge starts as `extracted` or `needs_verification`;
   team-authored knowledge starts as `draft`. Only `approved` knowledge may ever be consumed by
   an engine or the AI, and approval requires a `review` record.
3. **Paraphrase only.** No quotations, no reproduced figures, symbols or tables beyond the
   parameters needed. The source documents themselves are never committed.
4. **Mark inferences.** Anything not stated by the source goes into `inferences`.
5. **Units.** Building values in SI meters (`_m`, `_m2`); drawing values in sheet millimetres
   (`_paper_mm`); every numeric parameter carries a unit suffix. Quote scales (`"1:100"`).
6. **Scope.** The global `core` pack may cite a published source only for the *existence* of a
   concept. Source-specific statements live in scoped packs (e.g. the `spds` drawing profile).
7. **Immutable once used.** Change a used pack by adding `packs/<id>.v<n+1>/`. Any edit needs
   `pnpm knowledge:lock`; tests fail on a stale lock.
