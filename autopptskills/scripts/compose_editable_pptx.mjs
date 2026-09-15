#!/usr/bin/env node
/** Compose an editable PPTX from imagegen-derived assets and native objects. */

import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { createRequire } from "node:module";

const require = createRequire(import.meta.url);

function loadPptxGenJS() {
  const candidates = [];
  if (process.env.CODEX_PPTXGENJS) candidates.push(process.env.CODEX_PPTXGENJS);
  for (const base of (process.env.NODE_PATH || "").split(path.delimiter).filter(Boolean)) {
    candidates.push(path.join(base, "pptxgenjs"));
    candidates.push(path.join(base, "pptxgenjs", "dist", "pptxgen.cjs.js"));
  }
  candidates.push(
    path.join(
      os.homedir(),
      ".cache",
      "codex-runtimes",
      "codex-primary-runtime",
      "dependencies",
      "node",
      "node_modules",
      "pptxgenjs",
      "dist",
      "pptxgen.cjs.js",
    ),
  );
  try {
    return require("pptxgenjs");
  } catch {
    for (const candidate of candidates) {
      try {
        return require(candidate);
      } catch {
        // Continue through deterministic local candidates.
      }
    }
  }
  throw new Error("pptxgenjs is unavailable; set NODE_PATH or CODEX_PPTXGENJS");
}

const PptxGenJS = loadPptxGenJS();

function loadJSZip() {
  const candidates = [];
  for (const base of (process.env.NODE_PATH || "").split(path.delimiter).filter(Boolean)) {
    candidates.push(path.join(base, "jszip"));
  }
  candidates.push(
    path.join(
      os.homedir(),
      ".cache",
      "codex-runtimes",
      "codex-primary-runtime",
      "dependencies",
      "node",
      "node_modules",
      "jszip",
    ),
  );
  try {
    return require("jszip");
  } catch {
    for (const candidate of candidates) {
      try {
        return require(candidate);
      } catch {
        // Continue through deterministic local candidates.
      }
    }
  }
  throw new Error("jszip is unavailable; set NODE_PATH to the bundled Node dependencies");
}

const JSZip = loadJSZip();

function die(message) {
  process.stderr.write(`${message}\n`);
  process.exit(2);
}

function parseArgs(argv) {
  const positional = [];
  let report = null;
  for (let i = 0; i < argv.length; i += 1) {
    if (argv[i] === "--report") {
      report = argv[++i];
    } else {
      positional.push(argv[i]);
    }
  }
  if (positional.length !== 2) {
    die("usage: node compose_editable_pptx.mjs <deck.json> <out.pptx> [--report report.json]");
  }
  return { deckPath: positional[0], outPath: positional[1], report };
}

function readDeck(deckPath) {
  const deck = JSON.parse(fs.readFileSync(deckPath, "utf8"));
  if (!Array.isArray(deck.slides) || deck.slides.length === 0) die("deck.json must contain slides[]");
  deck.slide_width_in = Number(deck.slide_width_in || 13.333333);
  deck.slide_height_in = Number(deck.slide_height_in || 7.5);
  deck.ref_width = Number(deck.ref_width || 0);
  deck.ref_height = Number(deck.ref_height || 0);
  deck.units = deck.units || "fraction";
  deck.assets_dir = path.resolve(deck.assets_dir || path.dirname(path.resolve(deckPath)));
  if (deck.component_manifest) {
    const manifestPath = path.isAbsolute(deck.component_manifest)
      ? deck.component_manifest
      : path.join(deck.assets_dir, deck.component_manifest);
    if (!fs.existsSync(manifestPath)) die(`component manifest not found: ${manifestPath}`);
    deck._componentManifestPath = manifestPath;
    try {
      deck._componentManifest = JSON.parse(fs.readFileSync(manifestPath, "utf8"));
    } catch (error) {
      die(`component manifest is not valid JSON: ${manifestPath}`);
    }
  }
  return deck;
}

function cleanColor(value, fallback = "FFFFFF") {
  const text = String(value || fallback).replace(/^#/, "").toUpperCase();
  return /^[0-9A-F]{6}$/.test(text) ? text : fallback;
}

function transparency(opacity, fallback = 0) {
  if (opacity === undefined || opacity === null) return fallback;
  const normalized = Math.max(0, Math.min(1, Number(opacity)));
  return Math.round((1 - normalized) * 100);
}

function shadowOptions(value) {
  if (!value || typeof value !== "object" || Array.isArray(value)) return undefined;
  const type = ["outer", "inner", "none"].includes(String(value.type))
    ? String(value.type)
    : "outer";
  const shadow = { type };
  if (value.color !== undefined) shadow.color = cleanColor(value.color, "000000");
  for (const key of ["opacity", "blur", "angle", "offset"]) {
    if (value[key] !== undefined && Number.isFinite(Number(value[key]))) {
      const numeric = Number(value[key]);
      // PptxGenJS currently applies defaults with `value || fallback`, so an
      // explicit zero would otherwise become a visible 4 pt / 270 degree
      // shadow.  A positive epsilon serializes distance/blur/opacity to 0;
      // angle uses the nearest stable one-degree sentinel instead of 270.
      shadow[key] = numeric === 0 ? (key === "angle" ? 1 : 1e-6) : numeric;
    }
  }
  if (value.rotate_with_shape !== undefined) {
    shadow.rotateWithShape = Boolean(value.rotate_with_shape);
  }
  return shadow;
}

function coordinate(deck, item, key, axis) {
  const raw = Number(item[key] || 0);
  const slideExtent = axis === "x" ? deck.slide_width_in : deck.slide_height_in;
  const refExtent = axis === "x" ? deck.ref_width : deck.ref_height;
  if (deck.units === "fraction") return raw * slideExtent;
  if (deck.units === "pixel" || deck.units === "pixels" || deck.units === "px") {
    if (!refExtent) die(`ref_${axis === "x" ? "width" : "height"} is required for pixel units`);
    return (raw / refExtent) * slideExtent;
  }
  return raw;
}

function rawCoordinate(deck, raw, axis) {
  const slideExtent = axis === "x" ? deck.slide_width_in : deck.slide_height_in;
  const refExtent = axis === "x" ? deck.ref_width : deck.ref_height;
  if (deck.units === "fraction") return Number(raw || 0) * slideExtent;
  if (deck.units === "pixel" || deck.units === "pixels" || deck.units === "px") {
    if (!refExtent) die(`ref_${axis === "x" ? "width" : "height"} is required for pixel units`);
    return (Number(raw || 0) / refExtent) * slideExtent;
  }
  return Number(raw || 0);
}

function box(deck, item) {
  return {
    x: coordinate(deck, item, "x", "x"),
    y: coordinate(deck, item, "y", "y"),
    w: coordinate(deck, item, "w", "x"),
    h: coordinate(deck, item, "h", "y"),
  };
}

function resolveAsset(deck, file) {
  const resolved = path.isAbsolute(file) ? file : path.join(deck.assets_dir, file);
  if (!fs.existsSync(resolved)) die(`asset not found: ${resolved}`);
  return resolved;
}

function imageSource(file) {
  return { path: file };
}

function shapeType(pptx, type) {
  const map = {
    rect: pptx.ShapeType.rect,
    rounded_rect: pptx.ShapeType.roundRect,
    round_rect: pptx.ShapeType.roundRect,
    oval: pptx.ShapeType.ellipse,
    ellipse: pptx.ShapeType.ellipse,
    triangle: pptx.ShapeType.triangle,
    diamond: pptx.ShapeType.diamond,
    parallelogram: pptx.ShapeType.parallelogram,
    trapezoid: pptx.ShapeType.trapezoid,
    hexagon: pptx.ShapeType.hexagon,
    chevron: pptx.ShapeType.chevron,
    right_arrow: pptx.ShapeType.rightArrow,
    left_arrow: pptx.ShapeType.leftArrow,
    up_arrow: pptx.ShapeType.upArrow,
    down_arrow: pptx.ShapeType.downArrow,
  };
  return map[type] || pptx.ShapeType.roundRect;
}

function lineOptions(item) {
  const line = {
    color: cleanColor(item.line || item.fill || "0B5A45"),
    width: Number(item.line_width || 1),
    transparency: transparency(item.line_opacity, 0),
  };
  if (item.dash) line.dashType = item.dash;
  if (item.begin_arrow) line.beginArrowType = item.begin_arrow;
  if (item.end_arrow) line.endArrowType = item.end_arrow;
  return line;
}

function addNativeShape(slide, pptx, deck, item) {
  const type = String(item.type || "rounded_rect");
  let pos = box(deck, item);
  let flipH = false;
  let flipV = false;
  if ((type === "line" || type === "connector") && ["x1", "y1", "x2", "y2"].every((key) => item[key] !== undefined)) {
    const x1 = rawCoordinate(deck, item.x1, "x");
    const y1 = rawCoordinate(deck, item.y1, "y");
    const x2 = rawCoordinate(deck, item.x2, "x");
    const y2 = rawCoordinate(deck, item.y2, "y");
    pos = { x: Math.min(x1, x2), y: Math.min(y1, y2), w: Math.abs(x2 - x1), h: Math.abs(y2 - y1) };
    flipH = x2 < x1;
    flipV = y2 < y1;
  }
  const common = {
    ...pos,
    objectName: String(item.name || item.component_id || item.role || type),
    line: lineOptions(item),
    rotate: Number(item.rotation || 0),
    flipH,
    flipV,
  };
  const shadow = shadowOptions(item.shadow);
  if (shadow) common.shadow = shadow;
  if (type === "line" || type === "connector") {
    slide.addShape(pptx.ShapeType.line, common);
    return;
  }
  common.fill = item.fill
    ? { color: cleanColor(item.fill), transparency: transparency(item.opacity, 0) }
    : { color: "FFFFFF", transparency: 100 };
  slide.addShape(shapeType(pptx, type), common);
}

function isConnectorLike(item) {
  const type = String(item.type || "").toLowerCase();
  const role = String(item.role || "").toLowerCase();
  return ["line", "connector"].includes(type)
    || role.includes("connector")
    || role.includes("arrow-link");
}

function nativeShapeZIndex(item) {
  const explicit = Number(item.z_index);
  if (Number.isFinite(explicit)) return explicit;
  // Preserve the historical composer order when a deck does not opt in:
  // connectors first, followed by filled/native shapes.  Explicit z_index
  // lets a semantic reconstruction place editable panel fills below the
  // connector graph while keeping nodes and callouts above it.
  return isConnectorLike(item) ? 20 : 30;
}

function foregroundIconZIndex(item) {
  const explicit = Number(item.z_index);
  // Preserve the historical composer behavior for assets without an explicit
  // layer request: foreground pictures stay above native geometry.
  return Number.isFinite(explicit) ? explicit : 100;
}

function addText(slide, deck, item) {
  const pos = box(deck, item);
  const fontSize = Number(item.size || item.font_size || 18);
  const options = {
    ...pos,
    objectName: String(item.name || item.component_id || "editable-text"),
    fontFace: String(item.font || "Microsoft YaHei"),
    fontSize,
    color: cleanColor(item.color || "111111"),
    bold: Boolean(item.bold),
    italic: Boolean(item.italic),
    align: item.align || "left",
    valign: item.valign === "middle" ? "mid" : item.valign || "top",
    margin: [
      Number(item.margin_top || 0),
      Number(item.margin_right || 0),
      Number(item.margin_bottom || 0),
      Number(item.margin_left || 0),
    ],
    breakLine: false,
    fit: item.fit || "shrink",
    charSpacing: Number(item.char_spacing || 0),
    lineSpacingMultiple: Number(item.line_spacing_multiple || 1),
    paraSpaceAfter: Number(item.para_space_after_pt || 0),
    isTextBox: true,
    lang: item.lang || "zh-CN",
    transparency: transparency(item.opacity, 0),
  };
  const shadow = shadowOptions(item.shadow);
  if (shadow) options.shadow = shadow;
  const runs = item.runs;
  if (Array.isArray(runs) && runs.length) {
    const textRuns = runs.map((run) => ({
      text: String(run.text || ""),
      options: {
        fontFace: String(run.font || item.font || "Microsoft YaHei"),
        fontSize: Number(run.size || run.font_size || fontSize),
        color: cleanColor(run.color || item.color || "111111"),
        bold: run.bold === undefined ? Boolean(item.bold) : Boolean(run.bold),
        italic: run.italic === undefined ? Boolean(item.italic) : Boolean(run.italic),
        breakLine: Boolean(run.break_line),
        charSpacing: Number(run.char_spacing ?? item.char_spacing ?? 0),
        lang: run.lang || item.lang || "zh-CN",
      },
    }));
    slide.addText(textRuns, options);
  } else {
    slide.addText(String(item.text || ""), options);
  }
}

function normalizeParagraphProperties(xml) {
  let removed = 0;
  const normalized = xml.replace(/<a:p>([\s\S]*?)<\/a:p>/g, (_paragraph, body) => {
    let seenParagraphProperties = false;
    const normalizedBody = body.replace(
      /<a:pPr\b[^>]*?(?:\/>|>[\s\S]*?<\/a:pPr>)/g,
      (paragraphProperties) => {
        if (!seenParagraphProperties) {
          seenParagraphProperties = true;
          return paragraphProperties;
        }
        removed += 1;
        return "";
      },
    );
    return `<a:p>${normalizedBody}</a:p>`;
  });
  return { normalized, removed };
}

async function normalizeRichTextXml(pptxPath) {
  const archive = await JSZip.loadAsync(fs.readFileSync(pptxPath));
  const slideEntries = Object.values(archive.files).filter(
    (entry) => !entry.dir && /^ppt\/slides\/slide\d+\.xml$/.test(entry.name),
  );
  let paragraphPropertiesRemoved = 0;
  let slidesChanged = 0;
  for (const entry of slideEntries) {
    const xml = await entry.async("string");
    const result = normalizeParagraphProperties(xml);
    if (result.removed > 0) {
      archive.file(entry.name, result.normalized);
      paragraphPropertiesRemoved += result.removed;
      slidesChanged += 1;
    }
  }
  if (paragraphPropertiesRemoved === 0) {
    return { slides_changed: 0, paragraph_properties_removed: 0 };
  }

  const rewritten = await archive.generateAsync({
    type: "nodebuffer",
    compression: "DEFLATE",
    compressionOptions: { level: 6 },
  });
  const temporaryPath = `${pptxPath}.rich-text-${process.pid}.tmp`;
  try {
    fs.writeFileSync(temporaryPath, rewritten);
    fs.copyFileSync(temporaryPath, pptxPath);
  } finally {
    if (fs.existsSync(temporaryPath)) fs.unlinkSync(temporaryPath);
  }
  return {
    slides_changed: slidesChanged,
    paragraph_properties_removed: paragraphPropertiesRemoved,
  };
}

async function main() {
  const args = parseArgs(process.argv.slice(2));
  const deck = readDeck(args.deckPath);
  const pptx = new PptxGenJS();
  pptx.defineLayout({ name: "AUTOPPT_CUSTOM", width: deck.slide_width_in, height: deck.slide_height_in });
  pptx.layout = "AUTOPPT_CUSTOM";
  pptx.author = deck.author || "autopptskills";
  pptx.subject = deck.subject || "imagegen-first editable reconstruction";
  pptx.title = deck.title || "Editable PowerPoint";
  pptx.company = deck.company || "autopptskills";
  pptx.lang = "zh-CN";
  pptx.theme = {
    headFontFace: deck.head_font || "Microsoft YaHei",
    bodyFontFace: deck.body_font || "Microsoft YaHei",
    lang: "zh-CN",
  };

  const report = {
    deck: path.resolve(args.deckPath),
    output: path.resolve(args.outPath),
    slides: [],
    composer: "PptxGenJS",
    component_manifest: deck._componentManifestPath || null,
    component_manifest_objects: Array.isArray(deck._componentManifest?.objects)
      ? deck._componentManifest.objects.length : 0,
  };

  for (let index = 0; index < deck.slides.length; index += 1) {
    const spec = deck.slides[index];
    const slide = pptx.addSlide();
    const counts = {
      background: 0,
      connectors: 0,
      shapes: 0,
      vectors: 0,
      movable_images: 0,
      icons: 0,
      texts: 0,
    };
    const usedComponentIds = new Set();
    const knownComponentIds = new Set(
      Array.isArray(deck._componentManifest?.objects)
        ? deck._componentManifest.objects.map((item) => String(item.id))
        : [],
    );
    const markComponent = (item) => {
      if (item?.component_id) usedComponentIds.add(String(item.component_id));
    };
    const addIconAsset = (item) => {
      markComponent(item);
      const pos = box(deck, item);
      const resolved = resolveAsset(deck, item.file);
      const isVector = String(item.asset_type || "").toLowerCase() === "svg"
        || path.extname(resolved).toLowerCase() === ".svg";
      const defaultName = isVector ? "vector-svg::asset" : "imagegen-asset";
      // A bounded semantic asset may be sourced from a larger canonical image
      // while retaining a measured, movable output bbox.  PptxGenJS's crop
      // sizing uses the pre-crop image extent plus a source offset, so expose
      // this explicitly instead of forcing a second raster resample before
      // PowerPoint renders the slide.  The JSON's x/y/w/h remain the semantic
      // layout bbox used by audits; render_source_size/crop are only rendering
      // instructions for the embedded asset.
      let imagePos = { ...pos };
      if (Array.isArray(item.render_source_size) && item.render_source_size.length === 2
        && Array.isArray(item.render_source_crop) && item.render_source_crop.length === 4) {
        const [sourceW, sourceH] = item.render_source_size.map(Number);
        const [cropX, cropY, cropW, cropH] = item.render_source_crop.map(Number);
        if ([sourceW, sourceH, cropX, cropY, cropW, cropH].every(Number.isFinite)
          && sourceW > 0 && sourceH > 0 && cropW > 0 && cropH > 0
          && cropX >= 0 && cropY >= 0 && cropX + cropW <= sourceW && cropY + cropH <= sourceH) {
          imagePos = {
            ...pos,
            w: coordinate(deck, { w: sourceW }, "w", "x"),
            h: coordinate(deck, { h: sourceH }, "h", "y"),
            sizing: {
              type: "crop",
              w: pos.w,
              h: pos.h,
              x: coordinate(deck, { x: cropX }, "x", "x"),
              y: coordinate(deck, { y: cropY }, "y", "y"),
            },
          };
        }
      } else if (item.sizing && typeof item.sizing === "object") {
        imagePos.sizing = item.sizing;
      }
      slide.addImage({
        ...imageSource(resolved),
        ...imagePos,
        transparency: transparency(item.opacity, 0),
        objectName: String(item.name || item.component_id || item.role || defaultName),
        altText: String(item.editability_level || (isVector ? "convertible-vector" : "movable-image")),
      });
      counts.icons += 1;
      if (isVector) counts.vectors += 1;
      else counts.movable_images += 1;
    };

    if (spec.background) {
      slide.addImage({
        ...imageSource(resolveAsset(deck, spec.background)),
        x: 0,
        y: 0,
        w: deck.slide_width_in,
        h: deck.slide_height_in,
      objectName: String(spec.background_component_id || "imagegen-background"),
      });
      counts.background += 1;
    }

    const allIcons = Array.isArray(spec.icons) ? spec.icons : [];
    const backgroundIcons = allIcons.filter((item) => String(item.role || "").startsWith("pixel-anchored-background"));
    const foregroundIcons = allIcons.filter((item) => !String(item.role || "").startsWith("pixel-anchored-background"));
    for (const item of backgroundIcons) addIconAsset(item);

    const nativeShapes = Array.isArray(spec.shapes) ? spec.shapes : [];
    const orderedForeground = [
      ...nativeShapes.map((item, originalIndex) => ({
        kind: "shape",
        item,
        originalIndex,
        zIndex: nativeShapeZIndex(item),
        legacyRank: 0,
      })),
      ...foregroundIcons.map((item, originalIndex) => ({
        kind: "icon",
        item,
        originalIndex,
        zIndex: foregroundIconZIndex(item),
        legacyRank: 1,
      })),
    ].sort((left, right) => {
      const delta = left.zIndex - right.zIndex;
      if (delta) return delta;
      const legacyDelta = left.legacyRank - right.legacyRank;
      return legacyDelta || left.originalIndex - right.originalIndex;
    });
    for (const entry of orderedForeground) {
      if (entry.kind === "icon") {
        addIconAsset(entry.item);
        continue;
      }
      markComponent(entry.item);
      addNativeShape(slide, pptx, deck, entry.item);
      if (isConnectorLike(entry.item)) counts.connectors += 1;
      else counts.shapes += 1;
    }

    for (const item of spec.texts || []) {
      markComponent(item);
      addText(slide, deck, item);
      counts.texts += 1;
    }
    if (spec.notes && typeof slide.addNotes === "function") {
      slide.addNotes(String(spec.notes));
    }
    report.slides.push({
      slide: index + 1,
      native_shape_ordering: nativeShapes.some((item) => Number.isFinite(Number(item.z_index)))
        ? "explicit-z-index"
        : "legacy-default",
      foreground_object_ordering: orderedForeground.some((entry) => Number.isFinite(Number(entry.item.z_index)))
        ? "cross-layer-z-index"
        : "legacy-default",
      ...counts,
      component_manifest_unmapped: [...usedComponentIds].filter((id) => !knownComponentIds.has(id)),
      component_manifest_unused: [...knownComponentIds].filter((id) => !usedComponentIds.has(id)),
    });
  }

  fs.mkdirSync(path.dirname(path.resolve(args.outPath)), { recursive: true });
  await pptx.writeFile({ fileName: path.resolve(args.outPath) });
  report.rich_text_xml_normalization = await normalizeRichTextXml(path.resolve(args.outPath));
  if (args.report) {
    fs.mkdirSync(path.dirname(path.resolve(args.report)), { recursive: true });
    fs.writeFileSync(path.resolve(args.report), `${JSON.stringify(report, null, 2)}\n`, "utf8");
  }
  process.stdout.write(`${JSON.stringify(report)}\n`);
}

main().catch((error) => {
  process.stderr.write(`${error.stack || error.message}\n`);
  process.exit(2);
});
