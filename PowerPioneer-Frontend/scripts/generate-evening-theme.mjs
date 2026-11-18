/**
 * Generates src/theme-evening.generated.css — the dark "evening" theme.
 *
 * The app's stylesheets hard-code many light colours (white cards, pale tints,
 * dark navy text). Rather than hand-maintaining hundreds of overrides, this
 * script reads those stylesheets and, for every declaration with a colour,
 * emits a dark-mode version scoped to html[data-daypart="evening"]:
 *   - light surfaces / tints / borders  -> dark surfaces (keeping their hue)
 *   - dark text colours                 -> light text (keeping their hue)
 *   - mid-tone brand accents, shadows   -> left alone
 *
 * Re-run after changing styles.css / integration.css / timeline.css:
 *   npm run theme:evening
 */
import { readFileSync, writeFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import postcss from "postcss";

const SRC = join(dirname(fileURLToPath(import.meta.url)), "..", "src");
const INPUTS = ["styles.css", "integration.css", "timeline.css"];
const OUTPUT = "theme-evening.generated.css";
const SCOPE = 'html[data-daypart="evening"]';

const TEXT_PROPS = new Set(["color", "caret-color", "text-decoration-color"]);
const SURFACE_PROPS = /^(background|background-color|background-image|border|border-(top|right|bottom|left)(-color)?|border-color|outline(-color)?)$/;
const SVG_PROPS = new Set(["fill", "stroke"]);

// ---- colour helpers --------------------------------------------------------
const COLOR_RE = /#[0-9a-fA-F]{3,8}\b|rgba?\([^)]*\)|\bwhite\b|\bblack\b/g;

function parse(token) {
  if (token === "white") return [255, 255, 255, 1];
  if (token === "black") return [0, 0, 0, 1];
  if (token.startsWith("#")) {
    let h = token.slice(1);
    if (h.length === 3 || h.length === 4) h = [...h].map((c) => c + c).join("");
    const n = (i) => parseInt(h.slice(i, i + 2), 16);
    return [n(0), n(2), n(4), h.length === 8 ? n(6) / 255 : 1];
  }
  const parts = token.replace(/rgba?\(|\)/g, "").split(/[ ,/]+/).filter(Boolean).map(Number);
  return [parts[0], parts[1], parts[2], parts[3] ?? 1];
}

function toHsl([r, g, b]) {
  r /= 255; g /= 255; b /= 255;
  const max = Math.max(r, g, b), min = Math.min(r, g, b);
  const l = (max + min) / 2;
  if (max === min) return [0, 0, l];
  const d = max - min;
  const s = l > 0.5 ? d / (2 - max - min) : d / (max + min);
  const h = max === r ? (g - b) / d + (g < b ? 6 : 0) : max === g ? (b - r) / d + 2 : (r - g) / d + 4;
  return [h * 60, s, l];
}

function hslToCss(h, s, l, a) {
  const hsl = `${Math.round(h)} ${Math.round(s * 100)}% ${Math.round(l * 100)}%`;
  return a < 1 ? `hsl(${hsl} / ${+a.toFixed(3)})` : `hsl(${hsl})`;
}

/** Light surface / tint / border -> dark equivalent. null = keep as is. */
function darkSurface(token) {
  const [r, g, b, a] = parse(token);
  if (a === 0) return null;
  const [h, s, l] = toHsl([r, g, b]);
  if (l < 0.82) return null; // dark or mid-tone (brand colours, banners): keep
  if (a < 0.5 && l > 0.97) return null; // faint white overlay on a coloured block: keep
  const nl = Math.min(0.3, 0.155 + (1 - l) * 1.3);
  // Neutral whites/greys pick up the evening indigo so cards don't look flat grey.
  if (s < 0.08) return hslToCss(232, 0.3, nl, a);
  return hslToCss(h, Math.min(s, 0.42), nl, a);
}

/** Dark text -> light text. null = keep as is. */
function lightText(token) {
  const [r, g, b, a] = parse(token);
  const [h, s, l] = toHsl([r, g, b]);
  if (l >= 0.75) return null; // already light (e.g. white on a button)
  if (l >= 0.55) return hslToCss(h, s, Math.max(l, 0.7), a); // muted greys: lift a little
  return hslToCss(h, Math.min(s, 0.75), 0.93 - l * 0.4, a);
}

function transform(prop, value) {
  if (value.includes("var(")) return null;
  let fn = null;
  if (TEXT_PROPS.has(prop)) fn = lightText;
  else if (SURFACE_PROPS.test(prop) || SVG_PROPS.has(prop)) fn = darkSurface;
  if (!fn) return null;
  let changed = false;
  const out = value.replace(COLOR_RE, (tok) => {
    const next = fn(tok);
    if (next === null) return tok;
    changed = true;
    return next;
  });
  return changed ? out : null;
}

// ---- walk + emit ------------------------------------------------------------
function scopeSelector(selector) {
  return selector
    .split(",")
    .map((part) => {
      const p = part.trim();
      if (p.startsWith(":root")) return SCOPE + p.slice(":root".length);
      if (p.startsWith("html")) return SCOPE + p.slice("html".length);
      return `${SCOPE} ${p}`;
    })
    .join(",\n");
}

const outRoot = postcss.root();

for (const file of INPUTS) {
  const root = postcss.parse(readFileSync(join(SRC, file), "utf8"), { from: file });
  root.walkRules((rule) => {
    if (rule.parent.type === "atrule" && /keyframes$/i.test(rule.parent.name)) return;
    const decls = [];
    rule.each((node) => {
      if (node.type !== "decl") return;
      const next = transform(node.prop, node.value);
      if (next) decls.push(postcss.decl({ prop: node.prop, value: next, important: node.important }));
    });
    if (!decls.length) return;

    const scoped = postcss.rule({ selector: scopeSelector(rule.selector) });
    decls.forEach((d) => scoped.append(d));

    if (rule.parent.type === "atrule") {
      const at = postcss.atRule({ name: rule.parent.name, params: rule.parent.params });
      at.append(scoped);
      outRoot.append(at);
    } else {
      outRoot.append(scoped);
    }
  });
}

const header = `/* AUTO-GENERATED by scripts/generate-evening-theme.mjs — do not edit by hand.
 * Dark versions of the hard-coded colours in ${INPUTS.join(", ")}.
 * Hand-tuned evening tweaks live in daypart.css. */\n\n`;
writeFileSync(join(SRC, OUTPUT), header + outRoot.toString() + "\n");
console.log(`Wrote src/${OUTPUT} (${outRoot.nodes.length} rules)`);
