/* In-browser scoring: a faithful VADER port + the text escalation model.
 * Consumes window.SCORER_ASSETS (lexicon + trained weights). Kept in its own
 * file so it can be unit-tested against the Python pipeline (scripts/validate_scorer.js)
 * and lazy-loaded only when the Scorer tab opens.
 *
 * The VADER port mirrors vaderSentiment.SentimentIntensityAnalyzer.polarity_scores
 * line-for-line, minus emoji handling (complaint narratives are text). */
(function (global) {
  "use strict";
  const A = global.SCORER_ASSETS;
  if (!A) return;
  const LEX = A.vader.lexicon, BOOST = A.vader.boosters;
  const NEGSET = new Set(A.vader.negate), SPECIAL = A.vader.special_cases;
  const { B_INCR, B_DECR, C_INCR, N_SCALAR } = A.vader.constants;
  const PUNC = "!\"#$%&'()*+,-./:;<=>?@[\\]^_`{|}~";

  // ---- helpers ----
  const isUpper = (w) => w !== w.toLowerCase() && w === w.toUpperCase();
  function stripPunc(tok) {
    let s = 0, e = tok.length;
    while (s < e && PUNC.indexOf(tok[s]) >= 0) s++;
    while (e > s && PUNC.indexOf(tok[e - 1]) >= 0) e--;
    const stripped = tok.slice(s, e);
    return stripped.length <= 2 ? tok : stripped;
  }
  function wordsAndEmoticons(text) { return text.split(/\s+/).filter(Boolean).map(stripPunc); }
  function allcapDiff(words) {
    let caps = 0; for (const w of words) if (isUpper(w)) caps++;
    const d = words.length - caps; return d > 0 && d < words.length;
  }
  function negated(words) {
    for (const w of words) { const lw = String(w).toLowerCase();
      if (NEGSET.has(lw)) return true; if (lw.indexOf("n't") >= 0) return true; }
    return false;
  }
  function normalize(score, alpha) {
    alpha = alpha || 15; const n = score / Math.sqrt(score * score + alpha);
    return n < -1 ? -1 : n > 1 ? 1 : n;
  }
  function scalarIncDec(word, valence, isCapDiff) {
    let scalar = 0.0; const wl = word.toLowerCase();
    if (wl in BOOST) {
      scalar = BOOST[wl];
      if (valence < 0) scalar *= -1;
      if (isUpper(word) && isCapDiff) scalar += valence > 0 ? C_INCR : -C_INCR;
    }
    return scalar;
  }

  function negationCheck(valence, W, startI, i) {
    const L = W.map((w) => String(w).toLowerCase());
    if (startI === 0) { if (negated([L[i - 1]])) valence *= N_SCALAR; }
    if (startI === 1) {
      if (L[i - 2] === "never" && (L[i - 1] === "so" || L[i - 1] === "this")) valence *= 1.25;
      else if (L[i - 2] === "without" && L[i - 1] === "doubt") { /* valence unchanged */ }
      else if (negated([L[i - 2]])) valence *= N_SCALAR;
    }
    if (startI === 2) {
      if ((L[i - 3] === "never" && (L[i - 2] === "so" || L[i - 2] === "this")) ||
          (L[i - 1] === "so" || L[i - 1] === "this")) valence *= 1.25;
      else if (L[i - 3] === "without" && (L[i - 2] === "doubt" || L[i - 1] === "doubt")) { /* unchanged */ }
      else if (negated([L[i - 3]])) valence *= N_SCALAR;
    }
    return valence;
  }

  function leastCheck(valence, W, i) {
    const L = W.map((w) => String(w).toLowerCase());
    if (i > 1 && !(L[i - 1] in LEX) && L[i - 1] === "least") {
      if (L[i - 2] !== "at" && L[i - 2] !== "very") valence *= N_SCALAR;
    } else if (i > 0 && !(L[i - 1] in LEX) && L[i - 1] === "least") valence *= N_SCALAR;
    return valence;
  }

  function specialIdiomsCheck(valence, W, i) {
    const L = W.map((w) => String(w).toLowerCase());
    const onezero = `${L[i - 1]} ${L[i]}`;
    const twoonezero = `${L[i - 2]} ${L[i - 1]} ${L[i]}`;
    const twoone = `${L[i - 2]} ${L[i - 1]}`;
    const threetwoone = `${L[i - 3]} ${L[i - 2]} ${L[i - 1]}`;
    const threetwo = `${L[i - 3]} ${L[i - 2]}`;
    for (const seq of [onezero, twoonezero, twoone, threetwoone, threetwo]) {
      if (seq in SPECIAL) { valence = SPECIAL[seq]; break; }
    }
    if (L.length - 1 > i) { const zo = `${L[i]} ${L[i + 1]}`; if (zo in SPECIAL) valence = SPECIAL[zo]; }
    if (L.length - 1 > i + 1) { const zot = `${L[i]} ${L[i + 1]} ${L[i + 2]}`; if (zot in SPECIAL) valence = SPECIAL[zot]; }
    for (const ng of [threetwoone, threetwo, twoone]) if (ng in BOOST) valence += BOOST[ng];
    return valence;
  }

  function butCheck(W, sentiments) {
    const L = W.map((w) => String(w).toLowerCase());
    const bi = L.indexOf("but");
    if (bi < 0) return sentiments;
    return sentiments.map((s, si) => (si < bi ? s * 0.5 : si > bi ? s * 1.5 : s));
  }

  function sentimentValence(valence, W, isCapDiff, item, i, sentiments) {
    const il = item.toLowerCase();
    if (il in LEX) {
      valence = LEX[il];
      if (il === "no" && i !== W.length - 1 && (W[i + 1].toLowerCase() in LEX)) valence = 0.0;
      if ((i > 0 && W[i - 1].toLowerCase() === "no") ||
          (i > 1 && W[i - 2].toLowerCase() === "no") ||
          (i > 2 && W[i - 3].toLowerCase() === "no" &&
            (W[i - 1].toLowerCase() === "or" || W[i - 1].toLowerCase() === "nor")))
        valence = LEX[il] * N_SCALAR;
      if (isUpper(item) && isCapDiff) valence += valence > 0 ? C_INCR : -C_INCR;
      for (let startI = 0; startI < 3; startI++) {
        if (i > startI && !(W[i - (startI + 1)].toLowerCase() in LEX)) {
          let s = scalarIncDec(W[i - (startI + 1)], valence, isCapDiff);
          if (startI === 1 && s !== 0) s *= 0.95;
          if (startI === 2 && s !== 0) s *= 0.9;
          valence += s;
          valence = negationCheck(valence, W, startI, i);
          if (startI === 2) valence = specialIdiomsCheck(valence, W, i);
        }
      }
      valence = leastCheck(valence, W, i);
    }
    sentiments.push(valence);
    return sentiments;
  }

  function amplifyEp(text) { let c = (text.match(/!/g) || []).length; if (c > 4) c = 4; return c * 0.292; }
  function amplifyQm(text) { const c = (text.match(/\?/g) || []).length; return c > 1 ? (c <= 3 ? c * 0.18 : 0.96) : 0; }

  function siftScores(sentiments) {
    let pos = 0, neg = 0, neu = 0;
    for (const s of sentiments) { if (s > 0) pos += s + 1; else if (s < 0) neg += s - 1; else neu += 1; }
    return [pos, neg, neu];
  }

  function scoreValence(sentiments, text) {
    if (!sentiments.length) return { neg: 0, neu: 0, pos: 0, compound: 0 };
    let sum = sentiments.reduce((a, b) => a + b, 0);
    const punct = amplifyEp(text) + amplifyQm(text);
    if (sum > 0) sum += punct; else if (sum < 0) sum -= punct;
    const compound = normalize(sum);
    let [pos, neg, neu] = siftScores(sentiments);
    if (pos > Math.abs(neg)) pos += punct; else if (pos < Math.abs(neg)) neg -= punct;
    const total = pos + Math.abs(neg) + neu;
    return {
      neg: Math.round(Math.abs(neg / total) * 1000) / 1000,
      neu: Math.round(Math.abs(neu / total) * 1000) / 1000,
      pos: Math.round(Math.abs(pos / total) * 1000) / 1000,
      compound: Math.round(compound * 10000) / 10000,
    };
  }

  function sentiment(text) {
    text = (text || "").trim();
    const W = wordsAndEmoticons(text);
    const isCapDiff = allcapDiff(W);
    let sentiments = [];
    for (let i = 0; i < W.length; i++) {
      const item = W[i], il = item.toLowerCase();
      if (il in BOOST) { sentiments.push(0); continue; }
      if (i < W.length - 1 && il === "kind" && W[i + 1].toLowerCase() === "of") { sentiments.push(0); continue; }
      sentiments = sentimentValence(0, W, isCapDiff, item, i, sentiments);
    }
    sentiments = butCheck(W, sentiments);
    const r = scoreValence(sentiments, text);
    r.label = r.compound >= 0.05 ? "Positive" : r.compound <= -0.05 ? "Negative" : "Neutral";
    r.band = r.compound <= -0.6 ? "Very Negative" : r.compound <= -0.05 ? "Negative"
      : r.compound < 0.05 ? "Neutral" : r.compound < 0.6 ? "Positive" : "Very Positive";
    return r;
  }

  // ---- escalation text model (TF-IDF + LogisticRegression) ----
  const E = A.escalation;
  const STOP = new Set(E.stopwords);
  const VOCAB = new Map(); E.terms.forEach((t, i) => VOCAB.set(t, i));

  function tokenize(text) {
    const toks = (text.toLowerCase().match(/[a-z0-9_]{2,}/g) || []).filter((t) => !STOP.has(t));
    const grams = toks.slice();                       // unigrams
    for (let i = 0; i < toks.length - 1; i++) grams.push(toks[i] + " " + toks[i + 1]); // bigrams
    return grams;
  }
  const sigmoid = (z) => 1 / (1 + Math.exp(-z));

  function escalation(text) {
    const counts = new Map();
    for (const g of tokenize(text)) if (VOCAB.has(g)) counts.set(g, (counts.get(g) || 0) + 1);
    // sublinear tf-idf then L2 normalize
    const vec = [];
    let norm = 0;
    counts.forEach((c, term) => {
      const idx = VOCAB.get(term);
      const tf = E.sublinear ? 1 + Math.log(c) : c;
      const w = tf * E.idf[idx];
      vec.push([idx, term, w]); norm += w * w;
    });
    norm = Math.sqrt(norm) || 1;
    let z = E.intercept;
    const contrib = [];
    for (const [idx, term, w] of vec) {
      const x = w / norm, c = E.coef[idx] * x;
      z += c; contrib.push({ term, weight: c });
    }
    contrib.sort((a, b) => b.weight - a.weight);
    return {
      prob: sigmoid(z),
      matched: vec.length,
      top_up: contrib.filter((d) => d.weight > 0).slice(0, 6),
      top_down: contrib.filter((d) => d.weight < 0).slice(-6).reverse(),
    };
  }

  global.Scorer = { sentiment, escalation };
})(typeof window !== "undefined" ? window : globalThis);
