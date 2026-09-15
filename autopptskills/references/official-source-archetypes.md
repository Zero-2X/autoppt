# Official-source-inspired defense archetypes

Use these profiles when a thesis defense, research review, or formal technical
report needs the composure of an official university or funding context. They
are newly authored generic archetypes. They are not official templates, do not
claim affiliation or endorsement, and do not grant permission to reuse source
assets.

## Source and reuse contract

The source registry lives in `scripts/style_contracts.py`. Every active record
carries the source tier, access method and evidence, access date, license
status, de-identified extraction scope, and allowed extraction. The generated
prompt manifest preserves the same metadata under `style_reference`.

Source tiers used here:

- `tier_1_official_university_asset`: a template or presentation asset is
  published on an official university site;
- `tier_1_official_university_guidance`: presentation guidance is published by
  an official university unit;
- `tier_1_official_university_endpoint_context`: an official-domain endpoint is
  reachable, but its article body was not available to the audited CLI client;
  it is context evidence only and supplies no page-specific visual rules;
- `tier_1_official_funder_guidance`: review or application guidance is
  published by the official funding body.

Official publication is not an open license. For all sources below, no explicit
open redistribution or derivative-template license was identified. The
workflow therefore permits only high-level extraction of composition,
hierarchy, contrast, information density, and page rhythm. It forbids copying
the downloaded template, source master geometry, brand assets, campus imagery,
or source-specific content.

| Source | Tier | GET evidence on 2026-09-03 | License/reuse decision |
| --- | --- | --- | --- |
| [清华大学视觉形象识别：演示文稿模板](https://vi.tsinghua.edu.cn/mbyzy/dmt/yswgmb.htm) | `tier_1_official_university_asset` | `200`, 15,884 bytes, `text/html`; page title `演示文稿模板-清华大学视觉形象识别` | Pattern study only; no open redistribution or derivative-template license identified |
| [西安交通大学管理学院官方页面端点（正文未核验）](https://som.xjtu.edu.cn/info/1573/10316.htm) | `tier_1_official_university_endpoint_context` | `200`, 7,030 bytes, JavaScript browser-validation page titled `网站正在加载中...` | Endpoint/context evidence only; no article-title, content, visual-pattern, or reuse claim is made |
| [武汉理工大学党政办公室：校长办公会议题汇报模板（2025版）](http://dzb.whut.edu.cn/cyxz/201908/t20190827_1282380.shtml) | `tier_1_official_university_asset` | `200`, 9,375 bytes, `text/html`; page `h2` matches the link label, published 2025-09-19, with attachment `校长办公会汇报议题模版.pptx`; HEAD misreports `404` | Pattern study only; no open redistribution or derivative-template license identified |
| [中国科学技术大学教务处：PPT模板](https://www.teach.ustc.edu.cn/document/doc-misc/10319.html) | `tier_1_official_university_asset` | `200`, 43,541 bytes, `text/html`; page `h1` is `教务处PPT模板` and the footer identifies 中国科学技术大学教务处 | Pattern study only; no open redistribution or derivative-template license identified |
| [MIT NSE Communication Lab: Slide Design](https://mitcommlab.mit.edu/nse/commkit/slide-design/) | `tier_1_official_university_guidance` | `200`, 76,736 bytes, `text/html`; page `h1` is `Slide Design` and the footer links MIT Communication Lab | Guidance principles only; no template or brand-asset license granted |
| [申请规定（2026 年度科学基金项目申请配套材料）](https://www.nsfc.gov.cn/u/cms/www/202601/190844586k0w.pdf) | `tier_1_official_funder_guidance` | `200`, 1,009,614 bytes, `application/pdf`; first page title visually verified as `申请规定` | Application-rule discipline only; this PDF is not the complete 2026 project guide and grants no presentation-template or brand-asset license |

### Reproduce the access probe

Run the following PowerShell command for each registry URL, replacing
`<source-url>` with the exact source URL:

```powershell
curl.exe --request GET -L -sS --max-time 30 -A "Mozilla/5.0 (Windows NT 10.0; Win64; x64)" -o NUL -w "%{http_code}|%{size_download}|%{content_type}|%{url_effective}" "<source-url>"
```

The status and byte counts are point-in-time audit evidence, not permanent
availability guarantees. A future check should update `accessed_on` and the
recorded evidence rather than silently retaining a stale success.

For the Wuhan University of Technology URL, use `GET`. A separate `HEAD` probe
returned `404` while the full `GET` returned `200` with non-empty HTML. HEAD is
therefore not a valid health check for this origin. On 2026-09-03 the returned
article identity was `校长办公会议题汇报模板（2025版）`, not the older generic label
`行政汇报PPT模板发布页`; refreshes must trust the returned `h2` and attachment text.

The Xi'an Jiaotong University endpoint returns `200` to the reproducible GET,
but CLI clients receive a JavaScript browser-validation page. This proves the
official endpoint is active, not the article title or contents. It is therefore
excluded from active visual-authority inputs and contributes no composition,
hierarchy, palette, or asset rule. Content-level refreshes should use an
interactive browser and retain the same no-asset-reuse boundary.

The NSFC PDF was also visually checked rather than identified only from its
URL. Its first-page title is `申请规定`; the opening paragraph places it in the
2026 science-fund application context and separately tells applicants to read
the `指南`. The registry therefore records it as one application-rules component,
not as the complete 2026 guide.

GitHub examples may still inform implementation mechanics when their license is
compatible, but they are not treated as proof that a visual style is official.
The curated source set above intentionally uses first-party pages as the style
authority.

## GitHub maintenance survey

The following repository check was performed through the GitHub repository API
on 2026-09-03. It answers a different question from the official-source table:
whether there are maintained, inspectable presentation workflows that can
inform build mechanics. An organization-owned campus community repository is
still not the same thing as an official university administrative template.

| Repository | Owner / default branch | Latest commit at audit time | License | Workflow decision |
| --- | --- | --- | --- | --- |
| [`sjtug/SJTUBeamer`](https://github.com/sjtug/SJTUBeamer) | GitHub organization `sjtug` / `main` | `72a761384461`, 2026-05-20 | Apache-2.0 | Actively maintained and useful for modular theme structure, 16:9 academic hierarchy, examples, packaging, and reproducible compilation. Treat SJTUG as a campus technical community, not university template authority; do not copy identity assets into ImageGen prompts. |
| [`tuna/THU-Beamer-Theme`](https://github.com/tuna/THU-Beamer-Theme) | GitHub organization `tuna` / `master` | `061f088d1c7e`, 2020-12-11 | LPPL-1.3c | Useful historical evidence of a reusable theme package, but not continuously maintained at the audit date. It cannot satisfy the current-maintenance requirement and is not used as the active visual authority. |
| [`ustctug/ustcbeamer`](https://github.com/ustctug/ustcbeamer) | GitHub organization `ustctug` / `master` | `315cd8583707`, 2022-07-26 | LPPL-1.3c | Useful for studying separation between theme assets, content, and compilation, but not currently maintained enough to be the primary workflow reference. Official USTC web assets remain the first-party style source. |
| [`YarthsA/sjtu-beamer-ppt`](https://github.com/YarthsA/sjtu-beamer-ppt) | GitHub user `YarthsA` / `main` | `0423788331fb`, 2026-06-17 | no license declared | Recent agent-oriented presentation workflow, but the missing license and user-owned status prohibit code or asset reuse. Only the existence of prompt-to-build orchestration was noted. |
| [`robinren03/THU-modern-template`](https://github.com/robinren03/THU-modern-template) | GitHub user `robinren03` / `main` | `24fce72dc44d`, 2026-05-21 | LPPL-1.3c | Recent 16:9 template experiment, but a single user repository with little maintenance history is insufficient as an official or stable workflow reference. |

Reproduce the GitHub metadata, default-branch HEAD, and detected-license checks
with the public API, replacing the placeholders exactly:

```powershell
curl.exe -sS -L -H "Accept: application/vnd.github+json" -H "X-GitHub-Api-Version: 2022-11-28" -A "Codex-source-audit" "https://api.github.com/repos/<owner>/<repo>"
curl.exe -sS -L -H "Accept: application/vnd.github+json" -H "X-GitHub-Api-Version: 2022-11-28" -A "Codex-source-audit" "https://api.github.com/repos/<owner>/<repo>/commits/<default-branch>"
curl.exe -sS -L -H "Accept: application/vnd.github+json" -H "X-GitHub-Api-Version: 2022-11-28" -A "Codex-source-audit" "https://api.github.com/repos/<owner>/<repo>/license"
```

The 2026-09-03 refresh returned the same five HEAD commits, commit dates, and
license decisions shown above. The three group-owned repositories reported
GitHub owner type `Organization`; the two personal repositories reported owner
type `User`. These ownership fields document repository control only and do not
upgrade a campus community or personal repository into an official university
visual source.

The practical conclusion is deliberately conservative: use the maintained
`SJTUBeamer` repository only for generic workflow ideas such as reusable style
modules, deterministic builds, examples, and packaging. Use the official
university and funder pages above for visual-authority evidence. The AutoPPT
workflow adds requirements those repositories do not provide: one complete
ImageGen page per slide, semantic native-text/native-shape reconstruction,
background-cleanup evidence, real PowerPoint rendering, and page-level visual
non-regression against an accepted baseline.

Every active registry entry sets `extraction_scope` to
`generic_composition_only_deidentified` and `asset_reuse_allowed` to `false`.
This makes the allowed use machine-readable: composition and evidence patterns
may inform a new generic design, while source templates, logos, names, campus
imagery, marks, and exact geometry remain excluded.

## Mandatory identity ban

All five profiles prohibit visible or imitated:

- university emblems, seals, logos, names, or abbreviations;
- campus photographs, landmark buildings, or branded silhouettes;
- NSFC logos, wordmarks, emblems, form headers, or application layouts;
- labels claiming that the result is an official template;
- claims of university, laboratory, or funder affiliation or endorsement;
- exact source-master geometry, branded corner treatments, or source palette
  matching intended to impersonate the source.

A university or school name may appear only as source-verified presentation
content, for example on a thesis-defense cover. It must be listed verbatim in
both `exact_text` and `verified_identity_text` or `allowed_identity_text`. This
exception permits ordinary editable text only; it never permits a logo, seal,
campus image, branded palette, master geometry, affiliation claim, or
endorsement. Conflicting official-source style overrides fail closed.

Prompt builders disclose this exception only on a slide whose `exact_text`
contains the verified string. Every other slide receives an explicit
no-institution-text instruction, so deck-level provenance metadata cannot
accidentally seed a school name or identity treatment across the full deck.

Institution names remain in provenance metadata so the source can be audited,
but they are not inserted into the ImageGen visual prompt as design content.

## Archetype catalog

### `graduate_defense_navy`

For bachelor, master, and doctoral thesis defenses. It extracts formal defense
hierarchy, navy-on-light restraint, evidence density, and section rhythm from
official degree-defense and academic presentation sources. It uses a generic
navy and copper palette, not a university palette or master.

### `institutional_purple_light`

For academic defenses needing a distinctive light-field identity. It extracts
institutional restraint and light/accent relationships, then deliberately uses
a non-canonical aubergine palette. Exact official purple values, VI motifs,
seals, names, and campus imagery remain forbidden.

### `engineering_institutional_blue`

For engineering defenses, laboratory reports, and system reviews. It extracts
formal blue-on-light hierarchy and technical evidence framing from official
university presentation sources. It is more institutional than
`engineering_blueprint`, while still requiring a content-specific system,
mechanism, deployment, comparison, or result anchor.

### `science_dark_contrast`

For scientific defenses in dim rooms. It combines official scientific slide
guidance with generic academic rhythm: one message per slide, direct evidence
annotation, high contrast, and close legends. It does not copy an official
dark template or turn the page into cinematic science artwork.

### `nsfc_review_light`

For research proposals, opening reports, and funding-style reviews. It extracts
only the review logic of question, evidence, method, feasibility, risk, and
contribution. It is not an NSFC template, application form, or visual identity;
all NSFC marks and form-like headers are forbidden.

## Selection guidance

Choose one archetype for the deck, then retain the normal per-slide variation
rules from `style-system.md`.

| Context | Preferred archetype |
| --- | --- |
| General undergraduate or graduate thesis defense | `graduate_defense_navy` |
| Formal but distinctive humanities/interdisciplinary defense | `institutional_purple_light` |
| Engineering thesis, laboratory, or system defense | `engineering_institutional_blue` |
| Figure-heavy scientific defense in a dark room | `science_dark_contrast` |
| Proposal, opening report, or funding-review narrative | `nsfc_review_light` |

Do not select these profiles merely to borrow institutional prestige. If the
audience does not require an official-context tone, use the general profiles in
`style-system.md`.
