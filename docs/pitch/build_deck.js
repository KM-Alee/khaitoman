// AabFlow pitch deck generator (pptxgenjs). Every number is copied from stored runs, analyses or
// evidence files named in docs/TALKING_POINTS.md; screenshots are docs/pitch/shots/*.png taken by
// scripts/deck_shots.mjs from the real app. Animations and Morph transitions are added afterwards by
// docs/pitch/animate_deck.py. Run inside a container (see docs/pitch/README.md).
const path = require("path");
const fs = require("fs");
const pptxgen = require("pptxgenjs");

const HERE = __dirname;
const SHOTS = path.join(HERE, "shots");
const OUT = process.argv[2] || path.join(HERE, "AabFlow-pitch.pptx");

// Furrow & Flow, night edition: deep water ink, glowing teal, wheat gold for the one thing that matters.
const COL = {
  ink: "0B1514", // background
  ink2: "122523", // cards
  ink3: "1B3331", // card borders / quiet fills
  water: "3FB3BF",
  waterDeep: "087F8C",
  glow: "6FD6DF",
  wheat: "E0B154",
  wheatInk: "F0CF86",
  text: "E8EFEB",
  text2: "A9BCB8",
  text3: "7F9894",
  danger: "EC8A7C",
  veg: "86B996",
  white: "FFFFFF",
};
const HEAD = "Cambria";
const BODY = "Calibri";

const pres = new pptxgen();
pres.layout = "LAYOUT_WIDE"; // 13.333 x 7.5
pres.title = "AabFlow: test the season before you spend";
pres.author = "AabFlow team";
pres.company = "AabFlow";
pres.theme = { headFontFace: HEAD, bodyFontFace: BODY };

const W = 13.333;
const H = 7.5;
const M = 0.6;

pres.defineSlideMaster({
  title: "AAB_DARK",
  background: { color: COL.ink },
  objects: [
    { text: { text: "AabFlow · AICON 2026", options: { x: M, y: H - 0.42, w: 4, h: 0.3, fontFace: BODY, fontSize: 10, color: COL.text3, margin: 0 } } },
  ],
  slideNumber: { x: W - M - 0.6, y: H - 0.42, w: 0.6, h: 0.3, fontFace: BODY, fontSize: 10, color: COL.text3, align: "right" },
});

let n = 0;
function slide() {
  n += 1;
  return pres.addSlide({ masterName: "AAB_DARK" });
}

/** The motif: one glowing "water drop" circle that Morph carries from slide to slide. */
function drop(s, x, y, d, transparency = 72) {
  s.addShape(pres.shapes.OVAL, { x, y, w: d, h: d, fill: { color: COL.water, transparency }, line: { color: COL.glow, width: 0, transparency: 100 }, objectName: "!!drop" });
}

function title(s, text, sub) {
  s.addText(text, { x: M, y: 0.45, w: W - 2 * M, h: 0.8, fontFace: HEAD, fontSize: 36, bold: true, color: COL.text, margin: 0, isTextBox: true, objectName: "title" });
  if (sub) s.addText(sub, { x: M, y: 1.22, w: W - 2 * M, h: 0.5, fontFace: BODY, fontSize: 17, color: COL.text2, margin: 0, isTextBox: true, objectName: "anim-sub" });
}

function eyebrow(s, text, x = M, y = 0.25, color = COL.wheat) {
  s.addText(text.toUpperCase(), { x, y, w: 8, h: 0.25, fontFace: BODY, fontSize: 11, bold: true, color, charSpacing: 3, margin: 0, isTextBox: true });
}

function shotFrame(s, file, x, y, w, name = "anim-shot") {
  const p = path.join(SHOTS, file);
  if (!fs.existsSync(p)) throw new Error(`missing screenshot ${p}`);
  const h = (w * 1080) / 1920;
  s.addShape(pres.shapes.ROUNDED_RECTANGLE, {
    x: x - 0.06,
    y: y - 0.06,
    w: w + 0.12,
    h: h + 0.12,
    rectRadius: 0.16,
    fill: { color: COL.ink3 },
    line: { color: COL.waterDeep, width: 1 },
    shadow: { type: "outer", color: "000000", opacity: 0.45, blur: 18, offset: 6, angle: 90 },
    objectName: `${name}-frame`,
  });
  s.addImage({ path: p, x, y, w, h, rounding: false, objectName: name });
  return h;
}

function stat(s, x, y, w, big, label, color = COL.wheat, name = "anim-stat", bigSize = 54) {
  s.addText(big, { x, y, w, h: 0.95, fontFace: HEAD, fontSize: bigSize, bold: true, color, margin: 0, isTextBox: true, objectName: `${name}-n`, fit: "shrink" });
  s.addText(label, { x, y: y + 0.95, w, h: 0.75, fontFace: BODY, fontSize: 14, color: COL.text2, margin: 0, valign: "top", isTextBox: true, objectName: `${name}-l` });
}

function card(s, x, y, w, h, name) {
  s.addShape(pres.shapes.ROUNDED_RECTANGLE, {
    x,
    y,
    w,
    h,
    rectRadius: 0.18,
    fill: { color: COL.ink2 },
    line: { color: COL.ink3, width: 1 },
    shadow: { type: "outer", color: "000000", opacity: 0.35, blur: 12, offset: 4, angle: 90 },
    objectName: name,
  });
}

function iconCircle(s, x, y, glyph, name, color = COL.water) {
  s.addShape(pres.shapes.OVAL, { x, y, w: 0.62, h: 0.62, fill: { color, transparency: 78 }, line: { color, width: 1.25 }, objectName: `${name}-icon` });
  s.addText(glyph, { x, y, w: 0.62, h: 0.62, align: "center", valign: "middle", fontFace: BODY, fontSize: 20, bold: true, color, margin: 0, isTextBox: true, objectName: `${name}-glyph` });
}

const chartText = { catAxisLabelFontFace: BODY, valAxisLabelFontFace: BODY, dataLabelFontFace: BODY, titleFontFace: BODY, catAxisLabelColor: COL.text2, valAxisLabelColor: COL.text3, dataLabelColor: COL.text, titleColor: COL.text2 };

// 1 · Title ----------------------------------------------------------------------------------------
{
  const s = slide();
  drop(s, 7.9, -1.6, 7.2, 82);
  eyebrow(s, "AICON 2026 · irrigation and canal water planning", M, 1.25);
  s.addText("AabFlow", { x: M, y: 1.65, w: 6.4, h: 1.2, fontFace: HEAD, fontSize: 66, bold: true, color: COL.text, margin: 0, isTextBox: true, objectName: "title" });
  s.addText("Test the season before you spend.", { x: M, y: 2.85, w: 6.4, h: 1.3, fontFace: HEAD, fontSize: 34, italic: true, color: COL.glow, margin: 0, isTextBox: true, objectName: "anim-tagline" });
  s.addText("An AI planning agent that helps a village water committee decide which improvements to fund, before a single rupee is spent.", {
    x: M,
    y: 4.25,
    w: 5.9,
    h: 1.1,
    fontFace: BODY,
    fontSize: 17,
    color: COL.text2,
    margin: 0,
    isTextBox: true,
    objectName: "anim-lede",
  });
  shotFrame(s, "03-map-3d.png", 7.0, 1.55, 5.75, "anim-hero");
  s.addText("Real Sentinel-2 imagery · 30 AI-drawn fields · yield shown as height", { x: 7.0, y: 4.95, w: 5.75, h: 0.3, fontFace: BODY, fontSize: 11, color: COL.text3, margin: 0, isTextBox: true, objectName: "anim-caption" });
  s.addNotes(
    "Open: AabFlow is an AI planning agent for village water committees. One line: test the season before you spend. Everything you will see is computed from real runs; nothing is staged.",
  );
}

// 2 · The problem ----------------------------------------------------------------------------------
{
  const s = slide();
  drop(s, 9.6, 3.3, 3.2, 70);
  eyebrow(s, "The decision");
  title(s, "The tail farmer gets water last", "A few dozen farmers share one earthen watercourse and take fixed turns. The far end goes short first.");
  const pts = [
    ["1", "One shared channel", "Fields near the canal (the head) water first; the tail waits."],
    ["2", "A small budget", "Levelling, a pond, a canal repair, extra pumping: they can fund only some."],
    ["3", "Less water coming", "Every rupee and every turn matters more in a short year."],
  ];
  pts.forEach(([g, h, b], i) => {
    const y = 2.3 + i * 1.35;
    iconCircle(s, M, y, g, `anim-pt${i}`);
    s.addText(h, { x: M + 0.85, y: y - 0.04, w: 5.6, h: 0.42, fontFace: BODY, fontSize: 19, bold: true, color: COL.text, margin: 0, isTextBox: true, objectName: `anim-pt${i}-h` });
    s.addText(b, { x: M + 0.85, y: y + 0.38, w: 5.6, h: 0.6, fontFace: BODY, fontSize: 15, color: COL.text2, margin: 0, isTextBox: true, objectName: `anim-pt${i}-b` });
  });
  card(s, 7.6, 2.25, 5.1, 3.9, "anim-bigcard");
  s.addText("22%", { x: 7.95, y: 2.55, w: 4.4, h: 1.7, fontFace: HEAD, fontSize: 110, bold: true, color: COL.wheat, margin: 0, isTextBox: true, objectName: "anim-big" });
  s.addText("projected system-level water shortage for Rabi 2026–27 in Punjab and Sindh", {
    x: 7.95,
    y: 4.3,
    w: 4.4,
    h: 0.9,
    fontFace: BODY,
    fontSize: 16,
    color: COL.text,
    margin: 0,
    isTextBox: true,
    objectName: "anim-big-l",
  });
  s.addText("Source: Associated Press of Pakistan (APP), 2026", { x: 7.95, y: 5.45, w: 4.4, h: 0.3, fontFace: BODY, fontSize: 11, color: COL.text3, margin: 0, isTextBox: true, objectName: "anim-big-src" });
  s.addNotes("Warabandi: fixed weekly turns. The tail is served last. The committee can afford only some improvements, and a 22% shortage is projected (APP).");
}

// 3 · The twist ------------------------------------------------------------------------------------
{
  const s = slide();
  drop(s, -1.2, 5.2, 3.0, 76);
  eyebrow(s, "What our model found");
  title(s, "Optimising what exists quietly hurts the tail", "Same season, same water, same weather: three plans solved under identical conditions (pilot A, Rabi wheat 2027-28).");
  const cats = ["Today's routine (B0)", "Optimise existing (B1)", "AabFlow plan (P)"];
  card(s, M, 2.1, 5.95, 4.55, "anim-c1card");
  s.addChart(pres.charts.BAR, [{ name: "Wheat (t)", labels: cats, values: [129.7, 140.5, 154.1] }], {
    x: M + 0.15,
    y: 2.2,
    w: 5.65,
    h: 4.35,
    barDir: "col",
    chartColors: ["7A6F5C", "3E8A97", COL.water],
    showValue: true,
    dataLabelPosition: "outEnd",
    dataLabelFontSize: 14,
    dataLabelFormatCode: '0.0" t"',
    showTitle: true,
    title: "Wheat produced (tonnes)",
    titleFontSize: 14,
    valAxisHidden: true,
    valGridLine: { style: "none" },
    catGridLine: { style: "none" },
    catAxisLabelFontSize: 12,
    valAxisMinVal: 0,
    showLegend: false,
    ...chartText,
    objectName: "anim-chart1",
  });
  card(s, 6.75, 2.1, 5.98, 4.55, "anim-c2card");
  s.addChart(pres.charts.BAR, [{ name: "Tail field water", labels: cats, values: [61, 44, 61] }], {
    x: 6.9,
    y: 2.2,
    w: 5.68,
    h: 4.35,
    barDir: "col",
    chartColors: ["7A6F5C", COL.danger, COL.water],
    showValue: true,
    dataLabelPosition: "outEnd",
    dataLabelFontSize: 14,
    dataLabelFormatCode: '0"%"',
    showTitle: true,
    title: "Worst-off tail field: share of its water",
    titleFontSize: 14,
    valAxisHidden: true,
    valAxisMinVal: 0,
    valAxisMaxVal: 75,
    valGridLine: { style: "none" },
    catGridLine: { style: "none" },
    catAxisLabelFontSize: 12,
    showLegend: false,
    ...chartText,
    objectName: "anim-chart2",
  });
  s.addNotes(
    "Optimising only what exists grew 8.3% more wheat but cut the worst-off tail field from 61% to 44% of its water. AabFlow catches that. Runs: B0 run_8b6f, B1 run_6980, P run_5f2a.",
  );
}

// 4 · The plan -------------------------------------------------------------------------------------
{
  const s = slide();
  drop(s, 10.6, -0.9, 3.4, 74);
  eyebrow(s, "AabFlow's integrated plan");
  title(s, "More wheat, fairer water, under budget", "Proven best within its candidate options, then checked against the water rules.");
  const xs = [M, M + 4.15, M + 8.3];
  const items = [
    ["+18.8%", "more wheat than today's routine\n129.7 t → 154.1 t", COL.wheat],
    ["61%", "of its water for the worst-off tail field, back from 44% under 'optimise existing'", COL.glow],
    ["65%", "of the Rs 30 lakh budget used\nRs 19.5 lakh on 33 works", COL.text],
  ];
  items.forEach(([b, l, c], i) => {
    card(s, xs[i], 2.2, 3.85, 2.9, `anim-k${i}`);
    stat(s, xs[i] + 0.35, 2.5, 3.2, b, l, c, `anim-k${i}s`, 60);
  });
  card(s, M, 5.4, W - 2 * M, 1.0, "anim-honest");
  s.addText(
    [
      { text: "Honest trade-off: ", options: { bold: true, color: COL.wheatInk } },
      { text: "the plan pumps 8,288 m³ of groundwater where today's routine pumps none, within each well's cap. We say it before anyone asks.", options: { color: COL.text } },
    ],
    { x: M + 0.35, y: 5.5, w: W - 2 * M - 0.7, h: 0.8, fontFace: BODY, fontSize: 16, valign: "middle", margin: 0, isTextBox: true, objectName: "anim-honest-t" },
  );
  s.addNotes("+18.8% wheat, tail back to 61%, 65% of the budget. Say the groundwater cost out loud: it builds trust.");
}

// 5 · AI inside ------------------------------------------------------------------------------------
{
  const s = slide();
  drop(s, 5.6, 6.85, 2.0, 78);
  eyebrow(s, "Is AI the core? Yes: four engines");
  title(s, "It sees, predicts, plans and explains", "Perceive → simulate → decide → explain and act. Every fact below is read from stored evidence.");
  const eng = [
    ["S", "Sees", "931 → 30", "possible fields found on Sentinel-2 by Delineate Anything; review rules and a person kept the 30 clearest", COL.glow],
    ["P", "Predicts", "6.8 ms", "per yield estimate from a model we trained on GPU on 45,619 crop simulations (held-out error ≈ 7%)", COL.wheat],
    ["O", "Plans", "7,745", "field options searched by an exact optimiser; best plan proven in 0.37 s", COL.water],
    ["E", "Explains", "27 tools", "GPT-6 Luna runs the app's real tools, in English or Urdu; it never types a number", COL.veg],
  ];
  const cw = (W - 2 * M - 3 * 0.3) / 4;
  eng.forEach(([g, h, big, body, c], i) => {
    const x = M + i * (cw + 0.3);
    card(s, x, 2.15, cw, 4.45, `anim-e${i}`);
    iconCircle(s, x + 0.3, 2.45, g, `anim-e${i}`, c);
    s.addText(h, { x: x + 1.05, y: 2.5, w: cw - 1.2, h: 0.5, fontFace: BODY, fontSize: 20, bold: true, color: COL.text, margin: 0, isTextBox: true, objectName: `anim-e${i}-h` });
    s.addText(big, { x: x + 0.3, y: 3.35, w: cw - 0.5, h: 0.9, fontFace: HEAD, fontSize: 40, bold: true, color: c, margin: 0, isTextBox: true, objectName: `anim-e${i}-n`, fit: "shrink" });
    s.addText(body, { x: x + 0.3, y: 4.35, w: cw - 0.55, h: 2.0, fontFace: BODY, fontSize: 14, color: COL.text2, margin: 0, valign: "top", isTextBox: true, objectName: `anim-e${i}-b` });
  });
  s.addNotes(
    "Frame: AabFlow is an AI planning agent with four senses. Sees: 931 raw outlines to 30 reviewed. Predicts: LightGBM trained on 45,619 AquaCrop runs, 6.8 ms. Plans: CP-SAT searched 7,745 policies and proved the best. Explains: 27 real tools, Urdu.",
  );
}

// 6 · Sees -----------------------------------------------------------------------------------------
{
  const s = slide();
  drop(s, 12.1, 6.35, 1.6, 70);
  eyebrow(s, "Engine 1 · Sees", M, 0.25, COL.glow);
  title(s, "The AI found every field from space");
  shotFrame(s, "04-ai-raw-fields.png", M, 1.55, 7.6);
  stat(s, 8.75, 1.75, 4.0, "931", "possible field outlines the AI drew on one Sentinel-2 image (pilot A)", COL.wheat, "anim-s1");
  stat(s, 8.75, 3.6, 4.0, "30", "kept by our review rules, then checked by a person", COL.glow, "anim-s2");
  s.addText("Draw a new area and the same pipeline onboards it: pilot B v2 was published this way.", {
    x: 8.75,
    y: 5.45,
    w: 4.0,
    h: 0.9,
    fontFace: BODY,
    fontSize: 14,
    italic: true,
    color: COL.text2,
    margin: 0,
    isTextBox: true,
    objectName: "anim-s3",
  });
  s.addNotes("Dashed outlines are raw AI detections. Accuracy is not estimated (no reference boundaries); we report the review rate instead.");
}

// 7 · Predicts -------------------------------------------------------------------------------------
{
  const s = slide();
  drop(s, -0.8, -0.8, 2.6, 72);
  eyebrow(s, "Engine 2 · Predicts", M, 0.25, COL.wheat);
  title(s, "Drag a slider, get a crop yield in milliseconds");
  stat(s, M, 1.75, 4.0, "45,619", "exact AquaCrop simulations we ran and stored, then trained a model on (GPU)", COL.wheat, "anim-p1", 48);
  stat(s, M, 3.55, 4.0, "≈ 7%", "held-out error (wheat nMAE 0.071), gated on years the model never saw", COL.glow, "anim-p2", 48);
  s.addText("Labelled “approximate preview”; one click runs the exact crop model side by side.", {
    x: M,
    y: 5.45,
    w: 4.0,
    h: 0.9,
    fontFace: BODY,
    fontSize: 14,
    italic: true,
    color: COL.text2,
    margin: 0,
    isTextBox: true,
    objectName: "anim-p3",
  });
  shotFrame(s, "05-instant-crop.png", 5.05, 1.55, 7.7);
  s.addNotes("Live, the server measured 6–15 ms per estimate while dragging. The preview is never shown as exact.");
}

// 8 · Plans: the frontier --------------------------------------------------------------------------
{
  const s = slide();
  drop(s, 11.4, -0.6, 2.4, 74);
  eyebrow(s, "Engine 3 · Plans", M, 0.25, COL.water);
  title(s, "It tells a committee when not to spend", "Six budget settings, each solved to a proven optimum (frontier analysis).");
  card(s, M, 2.1, 7.6, 4.55, "anim-fcard");
  s.addChart(pres.charts.LINE, [{ name: "Wheat (t)", labels: ["Rs 0", "Rs 5 lakh", "Rs 15 lakh", "Rs 30 lakh", "Rs 80 lakh"], values: [140.5, 152.9, 153.3, 154.1, 154.6] }], {
    x: M + 0.2,
    y: 2.2,
    w: 7.2,
    h: 4.35,
    chartColors: [COL.water],
    lineSize: 3,
    lineDataSymbol: "circle",
    lineDataSymbolSize: 11,
    showValue: true,
    dataLabelPosition: "t",
    dataLabelFontSize: 13,
    dataLabelFormatCode: '0.0" t"',
    showTitle: true,
    title: "Wheat produced vs capital budget",
    titleFontSize: 14,
    valAxisMinVal: 135,
    valAxisMaxVal: 158,
    valAxisHidden: true,
    valGridLine: { style: "none" },
    catGridLine: { style: "none" },
    catAxisLabelFontSize: 13,
    showLegend: false,
    ...chartText,
    objectName: "anim-fchart",
  });
  stat(s, 8.6, 2.2, 4.1, "+12.4 t", "from the first Rs 5 lakh", COL.wheat, "anim-f1", 50);
  stat(s, 8.6, 3.85, 4.1, "+1.7 t", "from the next Rs 75 lakh", COL.text2, "anim-f2", 50);
  s.addText("A 95% tail floor at Rs 30 lakh is proven infeasible: an honest “no”, not a fake “yes”.", {
    x: 8.6,
    y: 5.55,
    w: 4.1,
    h: 0.9,
    fontFace: BODY,
    fontSize: 14,
    italic: true,
    color: COL.text2,
    margin: 0,
    isTextBox: true,
    objectName: "anim-f3",
  });
  s.addNotes("Frontier analysis ana_5bfa: 0 to 80 lakh. Returns flatten after 5 lakh. Each point is its own immutable run.");
}

// 9 · Bad years ------------------------------------------------------------------------------------
{
  const s = slide();
  drop(s, -1.9, 6.0, 2.6, 74);
  eyebrow(s, "Stress test");
  title(s, "The robust plan holds in all 9 tested seasons", "3 weather years × 3 canal supplies. A plan that breaks a water rule gets no yield, never a made-up one.");
  const rows = [
    ["Dry year", "55.3 t"],
    ["Typical year", "126.8 t"],
    ["Wet year", "175.7 t"],
  ];
  const cols = ["Normal turns", "22% water cut", "14-day closure"];
  const gx = M + 2.1;
  const cw = 2.15;
  cols.forEach((c, j) => s.addText(c, { x: gx + j * (cw + 0.15), y: 2.15, w: cw, h: 0.4, align: "center", fontFace: BODY, fontSize: 14, bold: true, color: COL.text2, margin: 0, isTextBox: true }));
  rows.forEach(([r, v], i) => {
    const y = 2.65 + i * 1.22;
    s.addText(r, { x: M, y, w: 1.95, h: 1.05, valign: "middle", fontFace: BODY, fontSize: 15, bold: true, color: COL.text, margin: 0, isTextBox: true });
    cols.forEach((_, j) => {
      const x = gx + j * (cw + 0.15);
      s.addShape(pres.shapes.ROUNDED_RECTANGLE, { x, y, w: cw, h: 1.05, rectRadius: 0.12, fill: { color: COL.waterDeep, transparency: 20 + i * 18 }, line: { color: COL.water, width: 1 }, objectName: `anim-cell${i}${j}` });
      s.addText([{ text: "✓ deliverable\n", options: { fontSize: 12, color: COL.text } }, { text: v, options: { fontSize: 20, bold: true, color: COL.white } }], {
        x,
        y,
        w: cw,
        h: 1.05,
        align: "center",
        valign: "middle",
        fontFace: BODY,
        margin: 0,
        isTextBox: true,
        objectName: `anim-cell${i}${j}-t`,
      });
    });
  });
  card(s, 9.55, 2.15, 3.18, 3.95, "anim-scard");
  s.addText(
    [
      { text: "Insurance with a price tag\n", options: { bold: true, fontSize: 17, color: COL.wheatInk, breakLine: true } },
      { text: "The robust plan (R) is chosen to survive the bad states. In a typical year it grows 126.8 t, below the typical-year plan's 154.1 t. The committee sees that price before choosing.", options: { fontSize: 14, color: COL.text } },
    ],
    { x: 9.8, y: 2.35, w: 2.75, h: 3.6, valign: "top", fontFace: BODY, margin: 0, isTextBox: true, objectName: "anim-stext" },
  );
  s.addNotes("Stress analysis ana_4e96 on the robust plan: deliverable in all 9 states. Production per weather year is the same across supply rows for this fixed plan.");
}

// 10 · Plan my season ------------------------------------------------------------------------------
{
  const s = slide();
  drop(s, 6.0, -1.2, 2.6, 76);
  eyebrow(s, "Engine 4 · Explains and acts", M, 0.25, COL.veg);
  title(s, "One sentence in, a season plan out");
  s.addText("“We have Rs 10 lakh. Don't hurt the tail farmers, and make sure it survives a dry year.”", {
    x: M,
    y: 1.35,
    w: W - 2 * M,
    h: 0.55,
    fontFace: HEAD,
    fontSize: 20,
    italic: true,
    color: COL.glow,
    margin: 0,
    isTextBox: true,
    objectName: "anim-goal",
  });
  shotFrame(s, "08-plan-season.png", M, 2.15, 7.75);
  const steps = [
    ["1", "Understands the goal", "reads the watercourse, solves the plan ladder and a what-if"],
    ["2", "Tests it", "budget frontier, stress test, who gains and who loses"],
    ["3", "Decides", "dated action plan and a one-page brief, every number traced"],
  ];
  steps.forEach(([g, h, b], i) => {
    const y = 2.2 + i * 1.12;
    iconCircle(s, 8.75, y, g, `anim-ps${i}`, COL.veg);
    s.addText(h, { x: 9.55, y: y - 0.05, w: 3.2, h: 0.4, fontFace: BODY, fontSize: 17, bold: true, color: COL.text, margin: 0, isTextBox: true, objectName: `anim-ps${i}-h` });
    s.addText(b, { x: 9.55, y: y + 0.33, w: 3.2, h: 0.65, fontFace: BODY, fontSize: 13, color: COL.text2, margin: 0, isTextBox: true, objectName: `anim-ps${i}-b` });
  });
  stat(s, 8.75, 5.45, 4.0, "93.7 s", "live, 13 real tool calls, all numbers validated", COL.wheat, "anim-pt", 40);
  s.addNotes(
    "Plan mode on the same copilot engine: 4 model rounds, tools in parallel. Its honest headline: choose the 10-lakh tail-protect plan, but it cannot be guaranteed through dry-year shortages; the robust variant was infeasible at that budget. Saved investigation replays offline; Run it live is the encore.",
  );
}

// 11 · Trust ---------------------------------------------------------------------------------------
{
  const s = slide();
  drop(s, 12.0, 6.3, 1.8, 72);
  eyebrow(s, "Why a committee can trust it");
  title(s, "Honest by construction");
  const rows = [
    ["#", "Every number is traced", "to a stored run, analysis or source, with its licence and hash. The copilot withholds any figure it cannot trace."],
    ["!", "Assumptions are labelled", "Water rights and costs are assumed and editable; the crop model is uncalibrated. Badges say so on screen."],
    ["⌁", "Works offline", "Planning, the crop model and the optimiser run locally in Docker. Cold start: 3.1 s to ready, 3.9 s to the tour."],
    ["✓", "Reproducible", "Published pilots re-derive byte for byte; make evidence-pack bundles the proof."],
  ];
  rows.forEach(([g, h, b], i) => {
    const y = 1.6 + i * 1.22;
    iconCircle(s, M, y, g, `anim-t${i}`, i === 1 ? COL.wheat : COL.water);
    s.addText(h, { x: M + 0.85, y: y - 0.04, w: 5.4, h: 0.4, fontFace: BODY, fontSize: 18, bold: true, color: COL.text, margin: 0, isTextBox: true, objectName: `anim-t${i}-h` });
    s.addText(b, { x: M + 0.85, y: y + 0.36, w: 5.4, h: 0.75, fontFace: BODY, fontSize: 13.5, color: COL.text2, margin: 0, isTextBox: true, objectName: `anim-t${i}-b` });
  });
  shotFrame(s, "10-trust.png", 7.15, 1.65, 5.6);
  s.addNotes("Limits, said first: uncalibrated crop model; assumed rights and costs; optimal only within generated candidates; copilot 30x3 evaluation (AT17) not yet run.");
}

// 12 · Take-home -----------------------------------------------------------------------------------
{
  const s = slide();
  drop(s, -0.9, -0.9, 2.8, 74);
  eyebrow(s, "What the committee takes home");
  title(s, "A one-page, dated action plan", "Who does what, when, at what cost, and who still goes short. Printed from the real run.");
  shotFrame(s, "09-report.png", M, 2.1, 7.1);
  const who = [
    ["Operator", "a WUA coordinator or extension officer"],
    ["First buyer", "a programme funding irrigation or resilience work"],
    ["Scales by", "onboarding: draw an area, AI finds fields, review, publish"],
  ];
  who.forEach(([h, b], i) => {
    const y = 2.2 + i * 1.3;
    card(s, 8.1, y, 4.63, 1.1, `anim-w${i}`);
    s.addText([{ text: `${h}\n`, options: { bold: true, color: COL.wheatInk, fontSize: 15, breakLine: true } }, { text: b, options: { color: COL.text, fontSize: 14 } }], {
      x: 8.35,
      y: y + 0.08,
      w: 4.2,
      h: 0.95,
      valign: "middle",
      fontFace: BODY,
      margin: 0,
      isTextBox: true,
      objectName: `anim-w${i}-t`,
    });
  });
  s.addNotes("Hold up the printed brief (make print-brief). IWMI's PRIAT works with 72 WUAs in Punjab: that is the channel.");
}

// 13 · Close ---------------------------------------------------------------------------------------
{
  const s = slide();
  drop(s, 7.9, -1.6, 7.2, 82);
  eyebrow(s, "Next step", M, 1.6);
  s.addText("Test the season before you spend.", { x: M, y: 2.0, w: 7.2, h: 1.9, fontFace: HEAD, fontSize: 48, bold: true, color: COL.text, margin: 0, isTextBox: true, objectName: "title" });
  s.addText("A supervised pilot with one Water User Association: calibrate the crop model, verify rights and costs, and put the plan in the committee's hands.", {
    x: M,
    y: 4.1,
    w: 6.6,
    h: 1.2,
    fontFace: BODY,
    fontSize: 18,
    color: COL.text2,
    margin: 0,
    isTextBox: true,
    objectName: "anim-ask",
  });
  s.addText("Who wants to be first?", { x: M, y: 5.45, w: 6.6, h: 0.6, fontFace: HEAD, fontSize: 26, italic: true, color: COL.wheat, margin: 0, isTextBox: true, objectName: "anim-who" });
  shotFrame(s, "01-landing.png", 7.6, 2.0, 5.15, "anim-close");
  s.addNotes("Close on the ask. Do not claim AT17, calibrated yields or measured rights or costs.");
}

pres.writeFile({ fileName: OUT }).then((f) => console.log(`wrote ${f} (${n} slides)`));
