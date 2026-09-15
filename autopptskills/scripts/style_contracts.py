#!/usr/bin/env python3
"""Shared visual contracts for ImageGen-first presentation decks."""
from __future__ import annotations

from copy import deepcopy
import re
from typing import Any


OFFICIAL_SOURCE_GET_REPRODUCTION = (
    'curl.exe --request GET -L -sS --max-time 30 '
    '-A "Mozilla/5.0 (Windows NT 10.0; Win64; x64)" '
    '-o NUL -w "%{http_code}|%{size_download}|%{content_type}|%{url_effective}" "<source-url>"'
)


OFFICIAL_REFERENCE_SOURCES: dict[str, dict[str, Any]] = {
    "tsinghua_vi_presentation": {
        "title": "演示文稿模板-清华大学视觉形象识别",
        "publisher": "清华大学",
        "url": "https://vi.tsinghua.edu.cn/mbyzy/dmt/yswgmb.htm",
        "source_tier": "tier_1_official_university_asset",
        "source_status": "active",
        "access_method": "GET",
        "accessed_on": "2026-09-03",
        "access_evidence": {
            "http_status": 200,
            "response_bytes": 15884,
            "content_type": "text/html",
            "effective_url": "https://vi.tsinghua.edu.cn/mbyzy/dmt/yswgmb.htm",
            "reproduction_command": OFFICIAL_SOURCE_GET_REPRODUCTION,
        },
        "license_status": "officially published; no explicit open redistribution or derivative-template license identified",
        "extraction_scope": "generic_composition_only_deidentified",
        "asset_reuse_allowed": False,
        "allowed_extraction": [
            "institutional restraint and projector-scale hierarchy",
            "high-level light-field and accent-color relationships after de-identification",
            "generic page rhythm without copying the template geometry or assets",
        ],
    },
    "xjtu_som_degree_defense": {
        "title": "西安交通大学管理学院官方页面端点（正文未核验）",
        "publisher": "西安交通大学管理学院",
        "url": "https://som.xjtu.edu.cn/info/1573/10316.htm",
        "source_tier": "tier_1_official_university_endpoint_context",
        "source_status": "active",
        "access_method": "GET",
        "accessed_on": "2026-09-03",
        "visual_authority_eligible": False,
        "access_evidence": {
            "http_status": 200,
            "response_bytes": 7030,
            "content_type": "text/html; charset=utf-8",
            "effective_url": "https://som.xjtu.edu.cn/info/1573/10316.htm",
            "reproduction_command": OFFICIAL_SOURCE_GET_REPRODUCTION,
            "content_access_note": "The endpoint is active but returns a JavaScript browser-validation page titled 网站正在加载中... to CLI clients. This record does not assert the article title or contents; content-level review requires an interactive browser.",
        },
        "license_status": "official endpoint only; page content and reuse terms were not inspected",
        "extraction_scope": "endpoint_context_only_content_unverified",
        "asset_reuse_allowed": False,
        "allowed_extraction": [
            "official domain and endpoint existence only; no page-specific composition, hierarchy, palette, or asset extraction until interactive verification",
        ],
    },
    "whut_administrative_presentation": {
        "title": "校长办公会议题汇报模板（2025版）",
        "publisher": "武汉理工大学党政办公室",
        "url": "http://dzb.whut.edu.cn/cyxz/201908/t20190827_1282380.shtml",
        "source_tier": "tier_1_official_university_asset",
        "source_status": "active",
        "access_method": "GET",
        "accessed_on": "2026-09-03",
        "access_evidence": {
            "http_status": 200,
            "response_bytes": 9375,
            "content_type": "text/html",
            "effective_url": "http://dzb.whut.edu.cn/cyxz/201908/t20190827_1282380.shtml",
            "reproduction_command": OFFICIAL_SOURCE_GET_REPRODUCTION,
            "head_probe_http_status": 404,
            "health_check_note": "HEAD is not supported reliably by this origin and misreports 404; use GET for access validation.",
            "verified_page_title": "校长办公会议题汇报模板（2025版）",
            "published_on": "2025-09-19",
            "attachment_title": "校长办公会汇报议题模版.pptx",
        },
        "license_status": "officially published; no explicit open redistribution or derivative-template license identified",
        "extraction_scope": "generic_composition_only_deidentified",
        "asset_reuse_allowed": False,
        "allowed_extraction": [
            "formal engineering-report hierarchy",
            "institutional blue restraint and divider rhythm after de-identification",
            "generic technical evidence framing without reusing template assets",
        ],
    },
    "ustc_academic_presentation": {
        "title": "教务处PPT模板",
        "publisher": "中国科学技术大学教务处",
        "url": "https://www.teach.ustc.edu.cn/document/doc-misc/10319.html",
        "source_tier": "tier_1_official_university_asset",
        "source_status": "active",
        "access_method": "GET",
        "accessed_on": "2026-09-03",
        "access_evidence": {
            "http_status": 200,
            "response_bytes": 43541,
            "content_type": "text/html; charset=UTF-8",
            "effective_url": "https://www.teach.ustc.edu.cn/document/doc-misc/10319.html",
            "reproduction_command": OFFICIAL_SOURCE_GET_REPRODUCTION,
        },
        "license_status": "officially published; no explicit open redistribution or derivative-template license identified",
        "extraction_scope": "generic_composition_only_deidentified",
        "asset_reuse_allowed": False,
        "allowed_extraction": [
            "academic title hierarchy and restrained page rhythm",
            "projector-oriented contrast and evidence placement",
            "generic scientific presentation patterns without copying institutional assets",
        ],
    },
    "mit_nse_slide_design": {
        "title": "Slide Design",
        "publisher": "MIT NSE Communication Lab",
        "url": "https://mitcommlab.mit.edu/nse/commkit/slide-design/",
        "source_tier": "tier_1_official_university_guidance",
        "source_status": "active",
        "access_method": "GET",
        "accessed_on": "2026-09-03",
        "access_evidence": {
            "http_status": 200,
            "response_bytes": 76736,
            "content_type": "text/html; charset=UTF-8",
            "effective_url": "https://mitcommlab.mit.edu/nse/commkit/slide-design/",
            "reproduction_command": OFFICIAL_SOURCE_GET_REPRODUCTION,
        },
        "license_status": "public guidance; no template, brand-asset, or derivative-layout license granted",
        "extraction_scope": "generic_composition_only_deidentified",
        "asset_reuse_allowed": False,
        "allowed_extraction": [
            "one-message-per-slide reasoning",
            "scientific evidence hierarchy and direct annotation",
            "contrast and legibility principles rather than visual assets",
        ],
    },
    "nsfc_2026_program_guide": {
        "title": "申请规定",
        "publisher": "国家自然科学基金委员会",
        "url": "https://www.nsfc.gov.cn/u/cms/www/202601/190844586k0w.pdf",
        "source_tier": "tier_1_official_funder_guidance",
        "source_status": "active",
        "access_method": "GET",
        "accessed_on": "2026-09-03",
        "access_evidence": {
            "http_status": 200,
            "response_bytes": 1009614,
            "content_type": "application/pdf",
            "effective_url": "https://www.nsfc.gov.cn/u/cms/www/202601/190844586k0w.pdf",
            "reproduction_command": OFFICIAL_SOURCE_GET_REPRODUCTION,
            "verified_document_title": "申请规定",
            "document_context_note": "A 2026 science-fund application-rules component that instructs applicants to read the Guide; it is not the complete 2026 program guide.",
        },
        "license_status": "public official guidance; no presentation-template or brand-asset reuse license granted",
        "extraction_scope": "generic_composition_only_deidentified",
        "asset_reuse_allowed": False,
        "allowed_extraction": [
            "application-condition, material, budget, research-integrity, ethics, and institutional-responsibility constraints",
            "conservative information hierarchy and traceable claim treatment",
            "rule-aware review discipline rather than any NSFC visual identity or application-form layout",
        ],
    },
}


OFFICIAL_SOURCE_ARCHETYPE_IDS = (
    "graduate_defense_navy",
    "institutional_purple_light",
    "engineering_institutional_blue",
    "science_dark_contrast",
    "nsfc_review_light",
)


FORBIDDEN_INSTITUTIONAL_IDENTITY_ELEMENTS = (
    "university_emblem_or_seal",
    "university_name_or_abbreviation",
    "campus_photograph_or_landmark",
    "nsfc_logo_wordmark_or_emblem",
    "official_template_label_or_affiliation_claim",
)


INSTITUTIONAL_IDENTITY_GUARD = (
    "This is a newly authored generic archetype, not an official template and not evidence of affiliation or endorsement. "
    "Do not show or imitate any university emblem or seal, unverified or decorative university or school name or "
    "abbreviation, campus photograph or landmark, NSFC logo, wordmark, or emblem, official template label, or "
    "source-specific master geometry."
)


OFFICIAL_SOURCE_OVERRIDE_RESERVED_KEYS = {
    "style_reference",
    "source_ids",
    "allowed_extraction",
    "forbidden_identity_elements",
    "identity_guard",
    "official_source_inspired",
    "official_template",
}


OFFICIAL_SOURCE_OVERRIDE_CONFLICT_MARKERS = (
    "logo",
    "emblem",
    "seal",
    "wordmark",
    "official template",
    "official master",
    "copied master",
    "copy the official",
    "university logo",
    "university emblem",
    "university seal",
    "campus photograph",
    "campus landmark",
    "nsfc logo",
    "nsfc wordmark",
    "nsfc emblem",
    "affiliation claim",
    "endorsement claim",
    "官方模板",
    "官方母版",
    "复制母版",
    "复刻母版",
    "照搬母版",
    "校徽",
    "校章",
    "校名",
    "大学名称",
    "校园照片",
    "校园地标",
    "基金委徽标",
    "基金委标志",
    "官方背书",
)


OFFICIAL_SOURCE_SAFETY_APPEND_FIELDS = {
    "style_contract",
    "background_rules",
    "layout_rules",
    "icon_rules",
    "quality_guardrails",
    "negative_prompt",
}


IDENTITY_LIKE_EXACT_TEXT_RE = re.compile(
    r"(?:[\u4e00-\u9fffA-Za-z0-9·\- ]{1,48}(?:大学|学院|研究院|实验室)|"
    r"国家自然科学基金|\bNSFC\b|\bUniversity\b|\bCollege\b|\bSchool of\b|\bInstitute of\b)",
    re.IGNORECASE,
)


STYLE_PROFILES: dict[str, dict[str, Any]] = {
    "academic_light": {
        "label": "Academic Light",
        "use_when": "general academic reports, project defenses, research proposals, and mixed technical audiences",
        "intentional_minimal": False,
        "design_density": "polished-medium",
        "style_contract": (
            "polished academic information design: white or very light paper background, "
            "low-saturation navy/teal palette, one restrained accent color, generous margins, "
            "a stable title band, measured grid alignment, content-specific evidence graphics, "
            "conclusion-led titles, and a mature evidence-first hierarchy"
        ),
        "palette": "background #F7F9FC/#FFFFFF; ink #172033; navy #173F5F; teal #2A7F8E; accent #D97745; gray #64748B",
        "typography": "large readable Chinese sans-serif, dark ink, strong title/body contrast, short labels, no tiny footnotes",
        "background_rules": "keep the background continuous and subordinate: paper, subtle grid, faint contour lines, or a soft two-tone wash; a source-grounded map, mechanism, or documentary crop may anchor the composition when it remains legible and does not compete with text",
        "layout_rules": "state one clear takeaway per slide and express it in the title when possible; use one dominant evidence composition with 1-3 supporting relationships; vary page archetypes across the deck; use cards only for genuinely independent regions; align text, diagrams, and connectors to a measured grid with generous breathing room",
        "icon_rules": "use small bounded flat icons with 1-3 colors, clear slide-scale contrast, and generous separation from text; keep local objects cleanly isolated for later extraction, but never sacrifice visual quality merely to force SVG tracing",
        "design_completion": "medium-to-high finish: every non-cover slide needs a content-specific primary evidence anchor, visible scale contrast, a clear reading path, and deliberate secondary detail; the page must feel authored rather than like a default title-and-card template",
        "quality_guardrails": "reject both meaningless spectacle and under-designed output: no decorative effects that compete with evidence, but also no empty placeholder canvas, generic icon grid, bare bullet list, or sparse card scaffold without a visual argument",
        "negative_prompt": "neon, cyberpunk, dramatic 3D render, giant abstract hero background, glowing particles, lens flare, excessive gradients, glassmorphism, ornate texture, busy wallpaper, floating decorative objects, unfinished template, generic icon grid, bare bullet-list slide, fake logo, watermark, page number",
    },
    "academic_minimal": {
        "label": "Academic Minimal",
        "use_when": "short thesis defenses, executive research updates, and sparse evidence pages where intentional simplicity improves focus",
        "intentional_minimal": True,
        "design_density": "intentional-low",
        "style_contract": "intentional minimal academic design: quiet white or pale paper field, precise dark typography, one restrained accent, one dominant evidence object or statement, disciplined alignment, and deliberately composed negative space",
        "palette": "background #FFFFFF/#F8FAFC; ink #172033; navy #24445F; accent #C96F45; gray #6B7280",
        "typography": "large readable Chinese sans-serif, decisive scale contrast, short copy, generous line spacing, no tiny footnotes",
        "background_rules": "use one continuous clean field with only a faint rule, grid, or source-grounded evidence crop; negative space must be intentional and balanced rather than simply empty",
        "layout_rules": "state one clear takeaway per slide; use one large evidence object, chart, equation, or concise statement; keep supporting elements to the minimum required for comprehension; vary crop, alignment, and scale across the deck without adding decorative clutter",
        "icon_rules": "use at most a few bounded symbols with strong silhouette and exact alignment; omit icons when they do not explain a relationship",
        "design_completion": "low element count but high finish: precise geometry, deliberate whitespace, clear scale contrast, and one unmistakable focal point; minimal never means default, blank, or unfinished",
        "quality_guardrails": "reject decoration added only to fill space, and reject accidental emptiness, weak alignment, tiny isolated content, generic title-plus-bullets, or a page that reads like a wireframe instead of a finished slide",
        "negative_prompt": "busy wallpaper, dense card grid, decorative icon swarm, gradient spectacle, cinematic hero scene, accidental empty canvas, weak alignment, default office template, placeholder blocks, fake logo, watermark, page number",
    },
    "deep_academic": {
        "label": "Deep Academic",
        "use_when": "research defenses, maritime or aerospace topics, and dim rooms where a dark field improves focus",
        "intentional_minimal": False,
        "design_density": "immersive-rich",
        "style_contract": "immersive but disciplined dark academic information design: deep navy field, muted blue/teal structure, one warm accent, source-grounded imagery, strong grid, conclusion-led titles, and evidence-first hierarchy",
        "palette": "background #101827/#172235; ink #F3F6FA; navy #2B5C88; teal #58A6A6; accent #E39A63; muted #A9B7C8",
        "typography": "large readable Chinese sans-serif, off-white text, restrained weight, short labels, no tiny footnotes",
        "background_rules": "use one continuous deep navy field; a source-grounded full-width photograph, map, interface, or scientific illustration may create atmosphere when darkened and integrated as evidence; keep overlays quiet enough for text and object separation",
        "layout_rules": "state one clear takeaway per slide and express it in the title when possible; use one dominant immersive evidence composition with a visible reading path; vary cinematic crop, architecture, comparison, and result silhouettes; use cards only for genuinely independent regions; preserve clear contrast and a measured grid",
        "icon_rules": "use small bounded flat icons with 1-3 muted colors, clear slide-scale contrast, and generous separation from text; keep local objects isolated for extraction without forcing every illustration into a traceable style",
        "design_completion": "high finish: combine one strong source-grounded scene, map, mechanism, or interface with restrained annotation, layered depth, and a memorable evidence path; the dark field should feel intentional and complete, not like a flat navy template",
        "quality_guardrails": "richness is allowed, but reject neon HUD stacks, sci-fi decoration, marketing-poster drama, and effects without evidence; also reject a plain dark rectangle with a few cards, weak focal hierarchy, or empty decorative space",
        "negative_prompt": "neon cyberpunk, holographic HUD, glowing particles, lens flare, rainbow gradients, noisy texture, ornamental wallpaper, marketing-poster key art, unsupported cinematic scene, plain dark template with a few cards, fake logo, watermark, page number",
    },
    "editorial_warm": {
        "label": "Editorial Warm",
        "use_when": "innovation projects, social research, design reviews, and business-academic presentations needing a humane tone",
        "intentional_minimal": False,
        "design_density": "editorial-medium-rich",
        "style_contract": "mature editorial presentation design: warm ivory paper, charcoal ink, muted terracotta and olive accents, asymmetric but measured composition, documentary-style evidence crops, conclusion-led titles, and deliberate rhythm",
        "palette": "background #FBF7F0/#FFFDFC; ink #2A2927; rust #B65F43; olive #66745A; accent #D89A62; gray #7A746C",
        "typography": "large readable Chinese sans-serif with occasional restrained serif-style display treatment in images; dark charcoal body text, short labels, no tiny footnotes",
        "background_rules": "use one continuous ivory or paper-like field with subtle grain, rules, or a documentary crop; full-bleed evidence is allowed when typography remains readable and the image carries source meaning rather than lifestyle decoration",
        "layout_rules": "state one clear takeaway per slide; favor a strong editorial axis, one evidence image or diagram, and short annotations; vary full-bleed evidence, split layouts, timelines, and comparison pages without repeating magazine-card mosaics",
        "icon_rules": "use simple bounded pictograms, line illustrations, or documentary cutouts in muted colors; isolate only objects that remain visually clean when moved independently",
        "design_completion": "medium-to-high finish: establish a recognisable editorial axis, purposeful crop, typographic contrast, and one evidence-led visual moment per slide; use whitespace as rhythm while retaining enough information to feel complete",
        "quality_guardrails": "reject fashion-magazine spectacle, scrapbook decoration, and lifestyle imagery without evidence; also reject a plain ivory page with a title and two generic boxes, timid scale, or uncomposed empty space",
        "negative_prompt": "luxury magazine styling, fashion collage, torn-paper decoration, excessive stickers, scrapbook clutter, sepia nostalgia, unsupported lifestyle hero photo, dramatic shadows, ornate serif paragraphs, plain ivory template with generic boxes, fake logo, watermark, page number",
    },
    "engineering_blueprint": {
        "label": "Engineering Blueprint",
        "use_when": "system architecture, mechanical, control, robotics, manufacturing, and engineering design reviews",
        "intentional_minimal": False,
        "design_density": "technical-rich",
        "style_contract": "high-finish engineering presentation design: white or pale blue-gray field, precise navy linework, cyan technical accents, measured datum cues, content-specific system illustrations, conclusion-led titles, and test-evidence hierarchy",
        "palette": "background #F5F8FB/#FFFFFF; ink #152A3A; navy #1F4E6D; cyan #2D8FA3; accent #D9824B; steel #6B7F8D",
        "typography": "large readable Chinese sans-serif, compact technical labels, tabular numerals, strong title/body contrast, and no blueprint-style microtext",
        "background_rules": "use one continuous pale technical field with a very faint grid, datum line, or contour cue; do not use a saturated dark-blue blueprint wallpaper or dense drafting marks",
        "layout_rules": "state one engineering conclusion per slide; use one dominant system, process, deployment scene, comparison, or test-result composition; combine orthographic components, measured arrows, evidence panels, and callouts into a clear reading path; reserve cards for truly separate subsystems",
        "icon_rules": "use bounded orthographic silhouettes, simplified component symbols, or flat technical icons with clear stroke weight at projector scale; accept vectors only after PowerPoint rendering",
        "design_completion": "high finish: each non-cover slide should show a specific system, device, deployment scene, mechanism, or measured result rather than generic cards; use precise alignment and enough technical detail to feel engineered without becoming a CAD screenshot",
        "quality_guardrails": "reject dense drafting noise, micro-dimensions, sci-fi interfaces, and decorative machinery; also reject a bare pale grid with generic icons, a thin flowchart without evidence, or excessive whitespace that makes the system look unfinished",
        "negative_prompt": "dark saturated blueprint wallpaper, dense CAD annotations, illegible dimensions, wireframe overload, sci-fi HUD, neon cyan glow, dramatic 3D exploded render, metallic texture, bare pale grid with generic icons, unfinished thin flowchart, fake logo, watermark, page number",
    },
    "clinical_clean": {
        "label": "Clinical Clean",
        "use_when": "biomedical, health, chemistry, life-science, and evidence-heavy experimental presentations",
        "intentional_minimal": False,
        "design_density": "evidence-rich-clean",
        "style_contract": "polished clinical-scientific presentation design: clean white field, cool blue-green structure, one coral emphasis, precise mechanism, cohort, chart, and study-flow graphics, conclusion-led titles, and high-legibility evidence hierarchy",
        "palette": "background #FFFFFF/#F6FAFA; ink #16313A; blue #2D6F8A; green #4D8B78; accent #D66F5B; gray #6D7F84",
        "typography": "large readable Chinese sans-serif, precise labels and units, dark ink, clear hierarchy, restrained bolding, and no tiny reference blocks",
        "background_rules": "use one continuous sterile white or very pale cool field with minimal scientific texture; no medical stock-photo wallpaper, molecule clouds, glowing DNA, or decorative laboratory scenes",
        "layout_rules": "state one evidence-backed conclusion per slide; prioritize a dominant study flow, mechanism, cohort, result, or comparison visual; annotate evidence directly, keep legends close to marks, and use supporting panels only when they clarify method or interpretation",
        "icon_rules": "use bounded flat clinical or laboratory symbols with restrained detail and strong silhouette; keep microscopy, molecular, or instrument imagery as bounded movable raster when vectorization would damage it",
        "design_completion": "medium-to-high finish: one precise evidence anchor plus directly attached labels, units, and interpretation; clean does not mean empty, so retain enough mechanism, cohort, image, or result detail to support the scientific claim",
        "quality_guardrails": "reject glowing biological clichés, medical stock-photo wallpaper, and glossy 3D spectacle; also reject sterile blank pages, generic molecule icons, disconnected cards, or charts without a visible interpretive hierarchy",
        "negative_prompt": "glowing DNA helix, floating molecules, medical stock-photo hero, futuristic laboratory, excessive cyan gradients, glossy 3D organs, decorative hexagons, sterile blank page, generic molecule icon grid, disconnected cards, fake journal logo, fake certification, watermark, page number",
    },
    "graduate_defense_navy": {
        "label": "Graduate Defense Navy",
        "use_when": "bachelor, master, and doctoral thesis defenses needing a formal, conservative, evidence-led academic tone",
        "intentional_minimal": False,
        "design_density": "formal-defense-medium-rich",
        "style_contract": "newly authored graduate-defense information design: quiet white or pale slate field, generic deep navy structure, restrained copper accent, formal section rhythm, conclusion-led titles, and a clear claim-evidence-defense hierarchy",
        "palette": "background #F7F8FA/#FFFFFF; ink #17212B; navy #17324D; blue #365C7D; accent #B7784A; gray #66727E",
        "typography": "large readable Chinese sans-serif, formal title hierarchy, compact evidence labels, tabular numerals, generous line spacing, and no thesis-page paragraphs or tiny references",
        "background_rules": "use one continuous quiet light field with restrained rules, a subtle navy edge structure, or a source-grounded evidence crop; keep the background non-semantic and avoid copying any university master, seal placement, or branded corner treatment",
        "layout_rules": "state one defensible conclusion per slide; use one dominant evidence anchor with up to three supporting relationships; alternate method, result, comparison, system, and synthesis silhouettes; reserve repeated cards for genuinely parallel evidence; maintain formal margins and a stable reading path",
        "icon_rules": "use bounded scholarly or domain-specific symbols with clear stroke weight and subdued color; keep simple frames and connectors measurable for reconstruction; never use a university crest, seal, or branded pictogram",
        "design_completion": "medium-to-high finish: each content slide needs a specific figure, chart, method, result, or system anchor plus concise interpretation; the deck should feel defense-ready without becoming an administrative template or ceremonial poster",
        "quality_guardrails": "reject ceremonial ornament, graduation imagery, institutional branding, copied master geometry, and generic corporate dashboards; also reject title-plus-bullet pages, undersized thesis screenshots, weak evidence hierarchy, or accidental empty space",
        "negative_prompt": "university emblem, university seal, unverified or decorative university or school name, campus photograph, campus landmark, NSFC logo or wordmark, official template label, copied master geometry, graduation cap decoration, ceremonial ribbon, corporate dashboard, tiny thesis screenshot, fake affiliation, watermark, page number",
        "source_ids": ("tsinghua_vi_presentation", "ustc_academic_presentation"),
        "allowed_extraction": (
            "formal degree-defense hierarchy",
            "generic navy-on-light contrast and restrained section rhythm",
            "evidence density and page-archetype cadence",
        ),
    },
    "institutional_purple_light": {
        "label": "Institutional Purple Light",
        "use_when": "humanities, computing, interdisciplinary, and institutional academic defenses needing a distinctive but restrained light-field identity",
        "intentional_minimal": False,
        "design_density": "institutional-medium",
        "style_contract": "newly authored light institutional presentation design: warm white field, non-canonical muted aubergine structure, soft plum secondary color, restrained bronze accent, disciplined title bands, and evidence-led asymmetry without source-institution branding",
        "palette": "background #FAF8FB/#FFFFFF; ink #281F2D; aubergine #5D3B67; plum #765078; accent #B68A55; gray #716A75",
        "typography": "large readable Chinese sans-serif, dark aubergine titles, neutral dark body text, measured weight contrast, short labels, and no decorative calligraphy or tiny footnotes",
        "background_rules": "use one continuous warm white or very pale lavender-gray field with restrained lines or translucent non-semantic blocks; the palette must remain generic and deliberately non-canonical, with no copied VI pattern, campus image, or branded master element",
        "layout_rules": "state one clear conclusion per slide; use one primary evidence visual, an asymmetric but measured grid, and concise annotations; vary split evidence, comparison, process, quotation, and synthesis silhouettes; avoid repeating ornamental purple cards",
        "icon_rules": "use bounded flat symbols in muted aubergine, gray, and one accent; preserve clean separation from text and frames; do not reproduce institutional seals, monograms, mascots, or campus silhouettes",
        "design_completion": "medium-to-high finish: create an authored academic rhythm through scale, edge alignment, evidence crops, and restrained color hierarchy; distinctive color must support navigation and interpretation rather than imitate a university identity system",
        "quality_guardrails": "reject exact institutional purple matching, copied VI geometry, seals, names, campus hero imagery, ceremonial motifs, and luxury styling; also reject a blank pale page with purple headings, generic card grids, timid scale, or evidence-free decoration",
        "negative_prompt": "university emblem, university seal, unverified or decorative university or school name, campus photograph, campus landmark, NSFC logo or wordmark, official template label, exact institutional purple, copied VI motif, copied master geometry, ceremonial architecture, luxury brochure, fake affiliation, watermark, page number",
        "source_ids": ("tsinghua_vi_presentation",),
        "allowed_extraction": (
            "institutional restraint and projector-scale hierarchy",
            "generic light-field and muted-purple relationships after de-identification",
            "high-level page rhythm without source palette matching or asset reuse",
        ),
    },
    "engineering_institutional_blue": {
        "label": "Engineering Institutional Blue",
        "use_when": "engineering thesis defenses, laboratory reports, system demonstrations, and technical reviews needing a formal university-report tone",
        "intentional_minimal": False,
        "design_density": "institutional-engineering-rich",
        "style_contract": "newly authored engineering institutional presentation design: white or pale blue-gray field, generic medium navy structure, muted cyan evidence accents, restrained orange emphasis, formal report rhythm, and specific systems, mechanisms, and measured results",
        "palette": "background #F5F8FA/#FFFFFF; ink #172833; navy #23506B; blue #3D718D; cyan #4B96A6; accent #C97943; gray #687C87",
        "typography": "large readable Chinese sans-serif, compact engineering labels, tabular numerals, strong title-body contrast, and no administrative fine print or drafting microtext",
        "background_rules": "use one continuous pale technical field with subtle datum cues, lines, or a low-contrast grid; do not copy an official university master, blue brand block, campus photograph, or exact administrative-template geometry",
        "layout_rules": "state one engineering judgment per slide; use one dominant system, mechanism, deployment, comparison, or test-result anchor; connect evidence with measured arrows and direct callouts; vary architecture, process, result, and validation silhouettes across the deck",
        "icon_rules": "use bounded orthographic symbols, components, and flat technical icons with projector-safe strokes; keep simple frames and connectors native-ready; never use a university emblem, wordmark, or branded building silhouette",
        "design_completion": "high finish: each content slide should contain a specific engineering object or evidence set, clear spatial logic, and concise interpretation; retain institutional composure without turning the page into a generic administrative report",
        "quality_guardrails": "reject copied official masters, university identity assets, dense CAD noise, sci-fi interfaces, decorative machinery, and generic blue corporate dashboards; also reject thin flowcharts, disconnected icons, timid evidence scale, or large unused regions",
        "negative_prompt": "university emblem, university seal, unverified or decorative university or school name, campus photograph, campus landmark, NSFC logo or wordmark, official template label, copied blue master, copied administrative layout, dark blueprint wallpaper, dense CAD annotations, sci-fi HUD, generic corporate dashboard, fake affiliation, watermark, page number",
        "source_ids": ("whut_administrative_presentation", "ustc_academic_presentation"),
        "allowed_extraction": (
            "formal engineering-report hierarchy",
            "generic blue-on-light restraint and divider rhythm",
            "technical evidence framing after complete de-identification",
        ),
    },
    "science_dark_contrast": {
        "label": "Science Dark Contrast",
        "use_when": "scientific and technical defenses in dim rooms where high contrast helps figures, mechanisms, maps, and experimental results",
        "intentional_minimal": False,
        "design_density": "scientific-dark-rich",
        "style_contract": "newly authored high-contrast scientific presentation design: deep charcoal-navy field, off-white type, muted blue-green evidence structure, one warm signal accent, direct annotation, and one-message-per-slide scientific reasoning",
        "palette": "background #111820/#18232D; ink #F4F6F7; blue #4F7E9B; teal #58A09A; accent #D58A56; muted #A9B5BE",
        "typography": "large readable Chinese sans-serif, off-white text, strong but restrained weight contrast, short scientific labels, visible units, and no dim gray microtext",
        "background_rules": "use one continuous charcoal-navy field; integrate only source-grounded scientific imagery, maps, interfaces, or plots as evidence; keep overlays quiet and separable, with no university identity, campus scene, or copied official-template geometry",
        "layout_rules": "state one scientific conclusion per slide; use one dominant figure, mechanism, result, or comparison with direct annotations and a visible reading path; vary evidence crop, process, architecture, and interpretation silhouettes; keep legends close to marks",
        "icon_rules": "use bounded scientific symbols with muted colors and high slide-scale contrast; preserve complex microscopy, interface, or photograph evidence as bounded assets when needed; do not use institutional emblems or decorative science clichés",
        "design_completion": "high finish: combine a specific evidence anchor with direct interpretation, deliberate contrast, and enough secondary context to support the claim; the dark field must clarify evidence rather than act as cinematic atmosphere",
        "quality_guardrails": "reject neon HUDs, glowing particles, cinematic key art, unsupported science imagery, copied university assets, and decorative space scenes; also reject a flat dark rectangle with small cards, low-contrast labels, detached legends, or evidence-free diagrams",
        "negative_prompt": "university emblem, university seal, unverified or decorative university or school name, campus photograph, campus landmark, NSFC logo or wordmark, official template label, neon cyberpunk, holographic HUD, glowing particles, cinematic key art, decorative galaxy, unsupported scientific image, flat dark template with small cards, fake affiliation, watermark, page number",
        "source_ids": ("mit_nse_slide_design", "ustc_academic_presentation"),
        "allowed_extraction": (
            "one-message-per-slide scientific reasoning",
            "direct evidence annotation and projector-scale contrast",
            "generic academic page rhythm without template or brand-asset reuse",
        ),
    },
    "nsfc_review_light": {
        "label": "NSFC Review Light",
        "use_when": "research proposals, funding-style reviews, opening reports, and defenses organized around scientific question, evidence, method, feasibility, risk, and contribution",
        "intentional_minimal": False,
        "design_density": "review-evidence-rich",
        "style_contract": "newly authored review-oriented academic presentation design: clean white field, neutral dark ink, generic navy structure, muted vermilion emphasis, traceable claim-evidence-method-feasibility logic, and conservative high-legibility composition",
        "palette": "background #FFFFFF/#F7F8FA; ink #202A33; navy #294F68; blue #4A7188; accent #B8614B; gold #AA8A54; gray #6F7B83",
        "typography": "large readable Chinese sans-serif, formal review hierarchy, compact method and evidence labels, precise numerals and units, and no form-like fine print or dense policy text",
        "background_rules": "use one continuous white or pale neutral field with restrained rules, evidence panels, or a faint analytical grid; do not reproduce an NSFC form, logo, wordmark, document header, application layout, or official visual identity",
        "layout_rules": "state one review judgment per slide; organize one dominant evidence anchor around question, gap, method, feasibility, risk, or contribution; show traceable relationships and comparison baselines; vary problem, mechanism, evidence, plan, risk, and synthesis silhouettes across the deck",
        "icon_rules": "use bounded generic research, method, risk, and evidence symbols with restrained color; prefer direct labels and simple geometry over decorative icons; never use the NSFC emblem, wordmark, seal, or an imitation application-form element",
        "design_completion": "high finish: each slide should expose a reviewable logic chain, source-backed evidence, and concise judgment; the deck may resemble the seriousness of formal funding review but must never appear to be an official NSFC template or submitted form",
        "quality_guardrails": "reject NSFC identity assets, copied application forms, official-looking headers, policy-document screenshots, invented approval marks, and generic consulting diagrams; also reject text-heavy form pages, disconnected cards, vague claims, or diagrams without evidence and feasibility context",
        "negative_prompt": "NSFC logo, NSFC wordmark, NSFC emblem, official NSFC template, copied application form, official-looking funder header, university emblem, university seal, unverified or decorative university or school name, campus photograph, campus landmark, approval stamp, fake affiliation, policy screenshot, generic consulting matrix, dense form text, watermark, page number",
        "source_ids": ("nsfc_2026_program_guide", "mit_nse_slide_design"),
        "allowed_extraction": (
            "review-oriented question, evidence, method, feasibility, and risk sequence",
            "conservative claim hierarchy and traceable evidence treatment",
            "scientific slide legibility principles without NSFC visual identity or form reuse",
        ),
    },
}


STYLE_ALIASES = {
    "light": "academic_light",
    "academic": "academic_light",
    "white": "academic_light",
    "minimal": "academic_minimal",
    "minimalist": "academic_minimal",
    "dark": "deep_academic",
    "deep": "deep_academic",
    "warm": "editorial_warm",
    "editorial": "editorial_warm",
    "engineering": "engineering_blueprint",
    "blueprint": "engineering_blueprint",
    "clinical": "clinical_clean",
    "science": "clinical_clean",
    "graduate_defense": "graduate_defense_navy",
    "navy_defense": "graduate_defense_navy",
    "purple_light": "institutional_purple_light",
    "institutional_blue": "engineering_institutional_blue",
    "science_dark": "science_dark_contrast",
    "nsfc": "nsfc_review_light",
    "review_light": "nsfc_review_light",
}


def _override_conflict_marker(text: str) -> str | None:
    normalized = text.casefold()
    ascii_tokens = re.sub(r"[_-]+", " ", normalized)
    for marker in OFFICIAL_SOURCE_OVERRIDE_CONFLICT_MARKERS:
        if marker.isascii():
            pattern = rf"(?<![a-z0-9_]){re.escape(marker.casefold())}(?:s)?(?![a-z0-9_])"
            if re.search(pattern, ascii_tokens):
                return marker
        elif marker in text:
            return marker
    return None


def _normalize_identity_text(value: Any, label: str) -> list[str]:
    if value in (None, "", []):
        return []
    raw_items = [value] if isinstance(value, str) else value
    if not isinstance(raw_items, (list, tuple)):
        raise ValueError(f"{label} must be a string or list of exact on-slide strings")
    items: list[str] = []
    for raw in raw_items:
        if not isinstance(raw, str) or not raw.strip():
            raise ValueError(f"{label} entries must be non-empty strings")
        item = raw.strip()
        if item not in items:
            items.append(item)
    return items


def _identity_text_exceptions(deck: dict[str, Any]) -> list[str]:
    items: list[str] = []
    for key in ("verified_identity_text", "allowed_identity_text"):
        for item in _normalize_identity_text(deck.get(key), f"deck.{key}"):
            if item not in items:
                items.append(item)
    return items


def _validate_official_source_overrides(deck: dict[str, Any], overrides: dict[str, Any]) -> None:
    reserved = OFFICIAL_SOURCE_OVERRIDE_RESERVED_KEYS.intersection(overrides)
    if reserved:
        raise ValueError(
            "official-source style overrides cannot replace protected provenance or identity fields: "
            + ", ".join(sorted(reserved))
        )

    direct_reserved = OFFICIAL_SOURCE_OVERRIDE_RESERVED_KEYS.intersection(deck)
    if direct_reserved:
        raise ValueError(
            "official-source deck fields cannot replace protected provenance or identity fields: "
            + ", ".join(sorted(direct_reserved))
        )

    override_values = {
        key: overrides[key] if key in overrides else deck[key]
        for key in (
            "intentional_minimal",
            "design_density",
            "style_contract",
            "palette",
            "typography",
            "background_rules",
            "layout_rules",
            "icon_rules",
            "design_completion",
            "quality_guardrails",
            "negative_prompt",
        )
        if key in overrides or key in deck
    }
    for key, value in override_values.items():
        if key == "intentional_minimal":
            if not isinstance(value, bool):
                raise ValueError("official-source intentional_minimal override must be a boolean")
            continue
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"official-source {key} override must be a non-empty string")
        marker = _override_conflict_marker(value)
        if marker:
            raise ValueError(
                "official-source style override conflicts with the protected identity boundary: "
                f"{marker!r}"
            )


def _identity_guard(identity_text: list[str]) -> str:
    if not identity_text:
        return INSTITUTIONAL_IDENTITY_GUARD
    allowed = " | ".join(identity_text)
    return (
        f"{INSTITUTIONAL_IDENTITY_GUARD} Verified identity-text exception: {allowed}. "
        "These exact source-backed strings may appear only as ordinary on-slide text. They are not identity assets, "
        "must not control the palette or master geometry, and do not permit a logo, seal, campus image, affiliation, "
        "or endorsement claim."
    )


def identity_prompt_guard(style_reference: dict[str, Any], exact_text: list[str]) -> str:
    if not style_reference.get("official_source_inspired"):
        return ""
    verified = style_reference.get("verified_identity_text", [])
    if not isinstance(verified, list):
        verified = []
    exact = {str(item).strip() for item in exact_text if str(item).strip()}
    allowed_on_slide = [
        item.strip()
        for item in verified
        if isinstance(item, str) and item.strip() in exact
    ]
    if allowed_on_slide:
        return _identity_guard(allowed_on_slide)
    return (
        f"{INSTITUTIONAL_IDENTITY_GUARD} No institution identity text is authorized on this slide; "
        "do not infer one from deck-level provenance metadata."
    )


def validate_identity_text_exceptions(style: dict[str, Any], exact_text: list[str]) -> None:
    reference = style.get("style_reference", {})
    if not reference.get("official_source_inspired"):
        return
    allowed = set(reference.get("verified_identity_text", []))
    exact = {str(item).strip() for item in exact_text if str(item).strip()}
    missing = sorted(allowed - exact)
    if missing:
        raise ValueError(
            "verified_identity_text/allowed_identity_text entries must exactly match an on-slide exact_text item: "
            + "; ".join(missing)
        )
    unapproved = sorted(
        item for item in exact if IDENTITY_LIKE_EXACT_TEXT_RE.search(item) and item not in allowed
    )
    if unapproved:
        raise ValueError(
            "identity-like exact text in an official-source profile must be explicitly source-verified via "
            "verified_identity_text or allowed_identity_text: "
            + "; ".join(unapproved)
        )


def style_profile_choices() -> tuple[str, ...]:
    """Return stable canonical profile IDs for CLIs and manifests."""
    return tuple(STYLE_PROFILES)


def get_style_profile(name: str | None = None) -> dict[str, Any]:
    key = (name or "academic_light").strip().lower().replace("-", "_")
    key = STYLE_ALIASES.get(key, key)
    if key not in STYLE_PROFILES:
        raise ValueError(f"unknown style profile: {name}; choose from {', '.join(sorted(STYLE_PROFILES))}")
    profile = deepcopy(STYLE_PROFILES[key])
    profile["profile_id"] = key
    source_ids = tuple(profile.get("source_ids", ()))
    profile["style_reference"] = {
        "reference_mode": "official-source-inspired-generic-archetype" if source_ids else "general-evidence-led-profile",
        "official_source_inspired": bool(source_ids),
        "official_template": False,
        "sources": [deepcopy(OFFICIAL_REFERENCE_SOURCES[source_id]) for source_id in source_ids],
        "allowed_extraction": list(profile.get("allowed_extraction", ())),
        "forbidden_identity_elements": list(FORBIDDEN_INSTITUTIONAL_IDENTITY_ELEMENTS) if source_ids else [],
        "identity_guard": INSTITUTIONAL_IDENTITY_GUARD if source_ids else "",
        "identity_text_policy": "source_verified_exact_text_only_not_identity_asset" if source_ids else "not_applicable",
        "verified_identity_text": [],
        "allowed_identity_text": [],
    }
    return profile


def merge_style_contract(deck: dict[str, Any], profile_name: str | None = None) -> dict[str, Any]:
    profile = get_style_profile(profile_name or deck.get("style_profile"))
    deck = dict(deck)
    deck["style_profile"] = profile["profile_id"]
    explicit_overrides = deck.get("style_overrides", {})
    if not isinstance(explicit_overrides, dict):
        raise ValueError("deck.style_overrides must be an object")
    official_source_inspired = profile["style_reference"]["official_source_inspired"]
    if official_source_inspired:
        _validate_official_source_overrides(deck, explicit_overrides)
    for key in (
        "intentional_minimal",
        "design_density",
        "style_contract",
        "palette",
        "typography",
        "background_rules",
        "layout_rules",
        "icon_rules",
        "design_completion",
        "quality_guardrails",
        "negative_prompt",
    ):
        override_present = key in explicit_overrides or key in deck
        override = explicit_overrides[key] if key in explicit_overrides else deck.get(key)
        if not override_present:
            deck[key] = profile[key]
        elif official_source_inspired and key in OFFICIAL_SOURCE_SAFETY_APPEND_FIELDS:
            deck[key] = f"{profile[key]}; Local project override: {override}"
        else:
            deck[key] = override

    identity_text = _identity_text_exceptions(deck)
    reference = deepcopy(profile["style_reference"])
    if identity_text and not official_source_inspired:
        raise ValueError(
            "verified_identity_text/allowed_identity_text is only valid for an official-source-inspired profile"
        )
    reference["verified_identity_text"] = identity_text
    reference["allowed_identity_text"] = identity_text
    reference["identity_guard"] = _identity_guard(identity_text) if official_source_inspired else ""
    deck["verified_identity_text"] = identity_text
    deck["allowed_identity_text"] = identity_text
    deck["style_reference"] = reference
    return deck
