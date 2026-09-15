# Evidence-led presentation style system

Use this reference when choosing an ImageGen direction, writing a deck-wide
style contract, generating several visual variants, or repairing a deck that is
either theatrical or visibly under-designed.

## Restraint is not the same as minimalism

Academic restraint removes effects that do not help the audience judge the
evidence. It does not require every slide to be plain, sparse, or minimal.

- `academic_minimal` is the only profile whose low element count is an
  intentional visual strategy.
- Every other profile should retain a mature evidence anchor, hierarchy,
  reading path, scale contrast, domain-specific visual language, and deliberate
  edge composition.
- A non-minimal slide that contains only a title, a few generic cards, stock
  icons, or unused empty space fails even if it is clean.
- A visually rich slide also fails when atmosphere, 3D, glow, collage, or
  decoration competes with the conclusion.

The target is not "as little design as possible." The target is the right amount
of source-backed design for the audience, venue, and evidence.

## Research and reference basis

The style system incorporates recurring guidance from scientific presentation
resources and public defense examples, including:

- MIT Communication Lab, [NSE slide design](https://mitcommlab.mit.edu/nse/commkit/slide-design/)
- MIT Communication Lab, [AeroAstro slide design](https://mitcommlab.mit.edu/aeroastro/commkit/slide-design/)
- Northwestern CLIMB, [Designing scientific presentation slides](https://www.northwestern.edu/climb/resources/oral-communication-skills/designing-PowerPoint-slides.html)
- Carnegie Mellon University, guidance on effective slide presentations
- official university thesis-defense and academic-report template collections
- public NSFC, graduate-defense, and discipline-competition case libraries

Public examples are used to extract composition patterns, not to copy protected
templates, logos, institutional branding, unsupported claims, or project
content. Useful recurring patterns are:

- one clear conclusion or judgment per slide;
- a title that states the takeaway when possible;
- one primary evidence anchor rather than a list of unrelated objects;
- simplified charts and diagrams with direct annotation;
- a visible reading path and projector-scale hierarchy;
- information density matched to the judges, room, and technical depth;
- visual variety across the deck without losing one coherent language.

These principles constrain quality but do not force one fixed visual template.

## Official-source-inspired archetypes

Five additive archetypes support formal thesis-defense and funding-review
contexts: `graduate_defense_navy`, `institutional_purple_light`,
`engineering_institutional_blue`, `science_dark_contrast`, and
`nsfc_review_light`. Their first-party source records, source tiers, access
dates, license decisions, allowed extraction, and mandatory identity bans are
defined in [official-source-archetypes.md](official-source-archetypes.md).

They are generic designs inspired by high-level composition principles, not
official templates. Never use them to reproduce or imply a university or NSFC
identity. University emblems or names, campus photography or landmarks, NSFC
marks, official-template labels, exact source-master geometry, and affiliation
claims are prohibited.

The only name exception is verified identity text required by the source
document, such as the university line on a defense cover. List the complete
string in both `exact_text` and `verified_identity_text` or
`allowed_identity_text`; it remains ordinary content and cannot authorize
identity assets or official-template styling.

## The bidirectional quality gate

Evaluate every ImageGen page on two independent risks.

### Spectacle risk

Fail when the slide uses non-evidence decoration as the main attraction:

- neon, cyberpunk, HUD stacks, lens flare, glowing particles, or rainbow light;
- dramatic 3D scenes, cinematic key art, fantasy backgrounds, or marketing
  poster composition;
- ornamental wallpaper, collage clutter, stock-photo hero imagery, or invented
  branding;
- visual effects that reduce readability or make semantic separation harder.

### Under-design risk

Fail when the slide looks like an unfinished scaffold:

- a title plus generic bullet list or repeated empty cards;
- a generic icon grid with no visual argument;
- weak focal hierarchy, timid scale, accidental whitespace, or no reading path;
- a plain color field with a few disconnected boxes;
- domain-neutral decoration where a system, mechanism, result, map, specimen,
  interface, or other source-backed evidence should anchor the page.

### Mature pass condition

A passing page normally contains:

1. one content-specific primary evidence anchor;
2. one clear claim and reading path;
3. deliberate scale contrast between title, evidence, and support;
4. domain-specific visual vocabulary;
5. purposeful crop, edge, alignment, or depth treatment;
6. enough secondary detail to feel complete without competing with the claim.

For `academic_minimal`, the same pass condition is achieved with fewer
objects: precise geometry, deliberate negative space, one unmistakable focal
point, and no accidental emptiness.

## Stable profiles

### `academic_light` — polished general default

Use for academic reports, proposals, competitions, and mixed audiences. Use a
white or very light paper field, low-saturation navy/teal, one warm accent,
measured alignment, and content-specific evidence graphics.

Design density is polished-medium. A map, mechanism, documentary crop, result,
or system illustration may anchor the composition when it is source-grounded
and remains subordinate to the conclusion.

Avoid generic card dashboards, blue gradient wallpaper, giant abstract hero
images, bare bullet lists, and unused empty space.

### `academic_minimal` — intentional low-density research

Use for short thesis defenses, executive research updates, and sparse evidence
pages where deliberate simplicity improves focus. Use quiet paper, precise dark
type, one restrained accent, one dominant evidence object or statement, and
carefully composed negative space.

Minimal means low object count with high finish. It never means a default Office
layout, a tiny isolated content block, weak alignment, or a blank canvas.

### `deep_academic` — immersive dark research

Use for technical defenses, maritime or aerospace topics, and dim rooms where a
dark field improves focus. Use deep navy, off-white type, muted blue/teal
structure, one warm accent, and a strong source-grounded scene, map, interface,
or scientific illustration.

Source-supported photographs, maps, and interfaces may create atmosphere when
darkened and integrated as evidence. Avoid neon HUDs, sci-fi ornament, glowing
particles, unsupported cinematic scenes, and a flat navy template with a few
cards.

### `editorial_warm` — humane innovation and social research

Use for design, social research, innovation, and business-academic narratives.
Use warm ivory, charcoal, muted terracotta/olive, asymmetric editorial axes,
purposeful crops, and documentary evidence.

Full-bleed evidence is allowed when it carries source meaning and leaves type
readable. Avoid fashion-magazine spectacle, scrapbook decoration, lifestyle
wallpaper, stickers, and a plain ivory title-plus-boxes scaffold.

### `engineering_blueprint` — technical richness without CAD noise

Use for architecture, control, robotics, manufacturing, and engineering design
reviews. Use a pale technical field, precise navy linework, cyan accents,
measured arrows, orthographic components, deployment scenes, and specific
system evidence.

The name does not authorize a dark saturated blueprint background. Avoid dense
CAD annotations, micro-dimensions, wireframe overload, sci-fi interfaces, a bare
pale grid with generic icons, and thin flowcharts without evidence.

### `clinical_clean` — precise biomedical and experimental evidence

Use for biomedical, health, chemistry, life science, and experimental results.
Use white/cool fields, blue-green structure, one coral emphasis, precise units,
study flows, mechanisms, cohorts, images, and directly annotated results.

Clean does not mean empty. Avoid glowing DNA, floating molecules, medical
stock-photo wallpaper, glossy 3D organs, generic molecule grids, disconnected
cards, and charts without interpretation.

## Profile selection

| Presentation context | Preferred profile | Alternative |
| --- | --- | --- |
| General project report, competition, or defense | `academic_light` | `deep_academic` for a dark room |
| Short executive update or deliberately sparse defense | `academic_minimal` | `academic_light` |
| Dense technical architecture or engineering review | `engineering_blueprint` | `academic_light` |
| Research defense with source imagery, maps, or interfaces | `deep_academic` | `academic_light` |
| Innovation, service design, or social research | `editorial_warm` | `academic_light` |
| Biomedical or experimental report | `clinical_clean` | `academic_light` |
| General bachelor, master, or doctoral thesis defense | `graduate_defense_navy` | `institutional_purple_light` |
| Formal engineering thesis or laboratory defense | `engineering_institutional_blue` | `graduate_defense_navy` |
| Figure-heavy scientific defense in a dark room | `science_dark_contrast` | `deep_academic` |
| Proposal, opening report, or funding-review narrative | `nsfc_review_light` | `academic_light` |

Use a profile as a baseline, then apply a small `style_overrides` object for
the project identity. Do not create a global profile for one accent color or one
slide-specific repair.

## Deck-wide style contract

Lock these before generating the first page:

- audience, judges, viewing environment, and presentation purpose;
- `style_profile` and whether `intentional_minimal` is true;
- `design_density`, `design_completion`, and `quality_guardrails`;
- palette, typography behavior, and projector-readable minimums;
- background discipline and allowed evidence imagery;
- diagram, chart, table, icon, and photography vocabulary;
- page archetype rhythm and no-repeat constraints;
- prohibited effects, unsupported branding, and source boundaries.

Every slide prompt remains self-contained, but repeats the compact deck-wide
contract so a regenerated page does not drift.

## Page archetype rhythm

Vary silhouettes while preserving one visual language. Useful archetypes are:

- conclusion plus one evidence visual;
- process or timeline;
- system architecture or deployment scene;
- two-way comparison;
- annotated chart or table;
- method or mechanism diagram;
- result plus interpretation;
- full-bleed source evidence with restrained annotation;
- sparse closing synthesis.

Do not repeat the same three-card or four-card grid on adjacent pages unless the
content is genuinely parallel.

## Prompt clauses

Shared spectacle-control clause:

> Professional academic presentation, not advertising key art. Every visual
> effect must support the evidence or reading path. No fantasy decoration,
> unsupported branding, invented metric, or effect that competes with the
> conclusion.

Shared design-completion clause:

> The selected profile must feel fully authored. Unless this is explicitly the
> academic_minimal profile, include one content-specific primary evidence
> anchor, a visible reading path, deliberate scale contrast, domain-specific
> graphics, and enough secondary detail to avoid an unfinished template or
> generic card scaffold.

If a generated page remains theatrical, remove non-evidence effects and
regenerate only that page while preserving its primary evidence anchor. If it
looks sparse or generic, enrich the composition with source-backed evidence,
annotations, comparison, mechanism, crop, or spatial relationships rather than
adding arbitrary decoration.
