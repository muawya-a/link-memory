# Third-party software and assets

The Link Memory project code is offered under Apache License 2.0; see [LICENSE](LICENSE). That license does not replace third-party licenses or grant rights to third-party names, hosted services, or data. This is a preliminary inventory, not a legal opinion or complete transitive dependency audit.

## Dependency license inventory

See [DEPENDENCY_LICENSE_INVENTORY.csv](DEPENDENCY_LICENSE_INVENTORY.csv) for versions resolved by the npm lockfile and the hashed Windows x64/CPython 3.12 Python locks, including the developer lock. npm license strings come from `package-lock.json`; Python strings come from PyPI release metadata or the exact upstream release license where noted. These are package declarations only, not legal conclusions, complete notice texts, or proof of ownership. Platform-specific npm optional packages are listed even when they are not installed on Windows.

## Included frontend dependencies

The direct dependencies pinned in `dashboard-react/package-lock.json` carry these declared license strings:

| Package | Version | Declared license |
| --- | ---: | --- |
| React | 18.3.1 | MIT |
| React DOM | 18.3.1 | MIT |
| Lucide React | 0.468.0 | ISC |
| Vite | 6.4.3 | MIT |
| TypeScript | 5.9.3 | Apache-2.0 |
| Tailwind CSS | 4.3.3 | MIT |
| `@vitejs/plugin-react` | 4.7.0 | MIT |
| `@tailwindcss/vite` | 4.3.3 | MIT |
| `@types/react` | 18.3.31 | MIT |
| `@types/react-dom` | 18.3.7 | MIT |
| `@types/node` | 22.20.4 | MIT |

These declarations are recorded in the lockfile; they are not a review of every transitive dependency, copyright notice, or patent term. The lockfile covers 164 npm package entries, including platform-specific optional packages. Review upstream notices before distributing a built bundle or vendoring packages.

## Transitive frontend packages

The npm lockfile records 164 package entries across platforms; Windows installs only a subset. Notable declarations include MPL-2.0 for Lightning CSS packages and CC-BY-4.0 for `caniuse-lite`. These are build dependencies, not checked-in source files; if a release bundles dependencies or generated assets, package-specific notices and attribution still need a final review.

## Optional dependencies and external services

- The Windows installer bundles the official CPython 3.13.16 embeddable runtime from python.org. The runtime's included `LICENSE.txt` must remain with the redistributable runtime files. It is not covered by the Link Memory Apache-2.0 license or by the optional Python dependency inventory below.
- Optional and developer Python packages are separated into feature-specific requirement files with hashed transitive locks for Windows x64/CPython 3.12. The reranker lock selects CPU PyTorch. Other platform/Python combinations require separately generated locks and install tests.
- `graphiti-core==0.30.2` is from the official Graphiti project under Apache-2.0. Keep Graphiti's upstream notices if redistributing the package; the project adapter does not grant Graphiti/Zep trademark rights or imply endorsement. Graphiti OSS is distinct from hosted Zep services.
- `mempalace==3.10.0` is published by the official MemPalace repository and PyPI under MIT. Preserve its copyright and license notice if redistributing it. This is an optional runtime dependency and is not copied into this repository.
- PyTorch `2.14.0` and Sentence Transformers `6.1.0` are pinned as an optional local reranker stack. Their declared license metadata is included in the inventory; review upstream notices before bundling.
- PyMuPDF `1.27.2.3` is pinned as optional local PDF text extraction. PyMuPDF is available under AGPL-3.0 or commercial terms; resolve the applicable terms before distributing or enabling PDF extraction in a commercial service.
- The `LongMemory` vendor source tree is not bundled. The previous checkout labels `providers/openmemory-src` as OpenMemory, but its code identifies itself as LongMemory and its exact upstream revision/nested notices remain unverified. The Link Memory adapter expects `/v1/ingest` and `/v1/recall`; do not claim compatibility with a different OpenMemory project until its contract is tested.
- The bundled Thmanyah Sans font files are excluded because [Thmanyah's official terms](https://ask.thmanyah.com/ar-SA/%D8%AE%D8%B7-%D8%AB%D9%85%D8%A7%D9%86%D9%8A%D8%A9-%D9%84%D9%84%D8%AC%D9%85%D9%8A%D8%B9) prohibit redistribution and hosting of the font files. Users may obtain the font from its official source under its own terms.
- Generated frontend bundles are excluded so no font or stale build artifact is accidentally redistributed.

## Typeface recommendation

The draft CSS uses the system stack `IBM Plex Sans Arabic`, then `Noto Sans Arabic`, `Segoe UI`, `Tahoma`, and `Arial`. Neither font is bundled, so machines without them use their installed fallback. Noto Sans Arabic is a practical sans-serif candidate; the [official Noto Arabic project](https://github.com/notofonts/arabic) states that its font software uses SIL Open Font License 1.1. If the project chooses to bundle either font, pin an upstream release, include the exact OFL and copyright notices, and verify the selected files are from the official source.

An additional suitable choice is IBM Plex Sans Arabic, a restrained humanist sans family designed for digital use. [IBM's official repository](https://github.com/IBM/plex) licenses it under SIL Open Font License 1.1; if selected, bundle the exact Arabic files and [IBM's license text](https://github.com/IBM/plex/blob/master/packages/plex-sans-arabic/LICENSE.txt). Noto Sans Arabic is more neutral; Noto Kufi Arabic is more geometric and is better considered for headings than dense interface text. These are visual candidates only; no font files are bundled in this draft.

Apache-2.0 was selected by the project owner for Link Memory. Before public release, confirm that the project owner has the rights to license every included project-authored file, UI asset, and modification. Third-party licenses do not grant ownership rights to the Link Memory project.
