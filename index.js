#!/usr/bin/env node
/**
 * NapiProjekt subtitles addon for Stremio.
 *
 * Best-effort implementation:
 * - Uses Cinemeta metadata (via the IMDb id that Stremio passes in many installs)
 * - Searches NapiProjekt public pages for a matching movie page
 * - Scores subtitle candidates by runtime similarity and release-name overlap
 * - Downloads the chosen subtitle through NapiProjekt API and serves it locally
 *
 * Limitations:
 * - Stremio subtitle requests do not include the actual video file bytes, only
 *   metadata like id, extra.videoHash (OpenSubtitles hash), extra.videoSize and filename.
 *   That means NapiProjekt's file-content hash cannot be computed exactly inside a
 *   Stremio addon without an additional local-file bridge.
 */

const express = require("express");
const crypto = require("crypto");
const { addonBuilder, getRouter } = require("stremio-addon-sdk");
const cheerio = require("cheerio");

const PORT = Number(process.env.PORT || 7000);
const PUBLIC_URL = (process.env.PUBLIC_URL || `http://127.0.0.1:${PORT}`).replace(/\/$/, "");
const DEFAULT_LANGUAGE = "pol";

// Small in-memory cache for subtitle blobs
const subtitleCache = new Map();

/** ---------- helpers ---------- */

function normText(value) {
  return String(value || "")
    .toLowerCase()
    .normalize("NFKD")
    .replace(/[\u0300-\u036f]/g, "")
    .replace(/[^a-z0-9]+/g, " ")
    .trim();
}

function tokenizeRelease(value) {
  const stop = new Set([
    "1080p","720p","2160p","480p","bluray","brrip","webrip","webdl","webr","hdrip",
    "x264","x265","h264","h265","aac","dts","proper","repack","yts","yify","blu",
    "dvdrip","bdrip","remux","polish","pl","napisy","sub","subs","movie","film"
  ]);
  return normText(value)
    .split(/\s+/)
    .filter(Boolean)
    .filter((t) => !stop.has(t));
}

function jaccard(aTokens, bTokens) {
  const a = new Set(aTokens);
  const b = new Set(bTokens);
  let intersection = 0;
  for (const t of a) if (b.has(t)) intersection++;
  const union = new Set([...a, ...b]).size;
  return union ? intersection / union : 0;
}

function parseDurationToSeconds(value) {
  if (!value) return null;
  const s = String(value).trim();
  const hhmmss = s.match(/(?:(\d+)\s*h)?\s*(?:(\d+)\s*mn?)?\s*(?:(\d+)\s*s)?/i);
  if (hhmmss && (hhmmss[1] || hhmmss[2] || hhmmss[3])) {
    const h = Number(hhmmss[1] || 0);
    const m = Number(hhmmss[2] || 0);
    const sec = Number(hhmmss[3] || 0);
    return h * 3600 + m * 60 + sec;
  }

  const colon = s.match(/(?:(\d+):)?(\d{1,2}):(\d{2}(?:\.\d+)?)/);
  if (colon) {
    const h = Number(colon[1] || 0);
    const m = Number(colon[2] || 0);
    const sec = Math.round(Number(colon[3]));
    return h * 3600 + m * 60 + sec;
  }

  const plain = s.match(/(\d{2,3})/);
  if (plain) {
    const n = Number(plain[1]);
    // heuristics: if it looks like minutes, convert to seconds
    return n <= 600 ? n * 60 : n;
  }
  return null;
}

function getRuntimeSeconds(meta) {
  if (!meta) return null;
  const candidates = [
    meta.runtime,
    meta.runtimeMinutes,
    meta.duration,
    meta.runTime,
    meta.length,
  ].filter(Boolean);

  for (const c of candidates) {
    const sec = parseDurationToSeconds(c);
    if (sec) {
      // If field is likely minutes, normalize if needed
      return sec < 60 * 5 ? sec * 60 : sec;
    }
  }
  return null;
}

async function fetchText(url, options = {}) {
  const res = await fetch(url, options);
  if (!res.ok) throw new Error(`HTTP ${res.status} for ${url}`);
  return await res.text();
}

async function fetchJson(url, options = {}) {
  const res = await fetch(url, options);
  if (!res.ok) throw new Error(`HTTP ${res.status} for ${url}`);
  return await res.json();
}

async function fetchCinemetaMeta(type, id) {
  const url = `https://v3-cinemeta.strem.io/meta/${type}/${encodeURIComponent(id)}.json`;
  try {
    const json = await fetchJson(url, { headers: { "accept": "application/json" } });
    return json?.meta || null;
  } catch {
    return null;
  }
}

async function duckSearchNapiprojekt(title, year) {
  const q = `site:napiprojekt.pl/napisy "${title}" ${year || ""}`.trim();
  const url = `https://html.duckduckgo.com/html/?q=${encodeURIComponent(q)}`;
  const html = await fetchText(url, {
    headers: {
      "user-agent": "Mozilla/5.0 (compatible; NapiProjektStremioAddon/1.0; +https://example.invalid)",
      "accept-language": "pl-PL,pl;q=0.9,en;q=0.8",
    },
  });

  const $ = cheerio.load(html);
  const results = [];
  $(".result").each((_, el) => {
    const a = $(el).find(".result__title a").first();
    const href = a.attr("href");
    const titleText = a.text().trim();
    if (href && /napiprojekt\.pl\/napisy/i.test(href)) {
      results.push({ href, titleText });
    }
  });

  return results;
}

async function searchNapiProjectPage(title, year) {
  const results = await duckSearchNapiprojekt(title, year);
  if (!results.length) return null;

  // Prefer the first direct subtitle/movie page.
  const direct = results.find((r) => /napisy/i.test(r.href)) || results[0];
  return direct.href;
}

function extractCandidateBlocks(html, pageUrl) {
  const $ = cheerio.load(html);
  const candidates = [];

  const pageText = $("body").text().replace(/\s+/g, " ").trim();

  // Collect napiprojekt hashes from both links and plain text
  const hashRegex = /napiprojekt:([a-f0-9]{32})/gi;
  const foundHashes = new Set();
  let m;
  while ((m = hashRegex.exec(html)) !== null) foundHashes.add(m[1]);

  // Try table rows first, because the subtitle pages tend to have a table of versions.
  $("tr").each((_, row) => {
    const rowText = $(row).text().replace(/\s+/g, " ").trim();
    if (!rowText) return;

    const rowHashes = [...rowText.matchAll(/napiprojekt:([a-f0-9]{32})/gi)].map((x) => x[1]);
    const rowHash = rowHashes[0] || null;
    const durationMatch = rowText.match(/(\d{1,2}:\d{2}:\d{2}(?:\.\d+)?|\d{1,2}:\d{2})/);
    const sizeMatch = rowText.match(/(\d+(?:[.,]\d+)?\s*(?:MiB|GiB|MB|GB))/i);

    const candidate = {
      hash: rowHash,
      text: rowText,
      durationText: durationMatch ? durationMatch[1] : null,
      sizeText: sizeMatch ? sizeMatch[1] : null,
      pageUrl,
      raw: rowText,
    };

    if (candidate.hash || candidate.durationText || candidate.sizeText) {
      candidates.push(candidate);
    }
  });

  // Fallback: generic hash occurrences when row parsing didn't catch it
  if (!candidates.length && foundHashes.size) {
    for (const hash of foundHashes) {
      candidates.push({
        hash,
        text: pageText,
        durationText: null,
        sizeText: null,
        pageUrl,
        raw: pageText,
      });
    }
  }

  return candidates;
}

async function fetchNapiprojektPage(url) {
  const html = await fetchText(url, {
    headers: {
      "user-agent": "Mozilla/5.0 (compatible; NapiProjektStremioAddon/1.0; +https://example.invalid)",
      "accept-language": "pl-PL,pl;q=0.9,en;q=0.8",
    },
  });
  return html;
}

function scoreCandidate(candidate, meta, filename) {
  const titleTokens = tokenizeRelease(meta?.name || meta?.title || "");
  const filenameTokens = tokenizeRelease(filename || "");
  const candidateTokens = tokenizeRelease(candidate.raw || candidate.text || "");

  let score = 0;

  // Prefer release overlap
  score += jaccard([...titleTokens, ...filenameTokens], candidateTokens) * 30;

  // Prefer duration closeness when we can parse it
  const movieRuntime = getRuntimeSeconds(meta);
  const subRuntime = parseDurationToSeconds(candidate.durationText);
  if (movieRuntime && subRuntime) {
    const diff = Math.abs(movieRuntime - subRuntime);
    // A subtitle that is within ~60s gets a strong boost; a big mismatch gets penalized.
    score += Math.max(0, 40 - diff / 30);
  }

  // Gentle preference for page title / explicit movie title presence
  const normalizedMetaName = normText(meta?.name || meta?.title || "");
  if (normalizedMetaName && normText(candidate.raw || candidate.text || "").includes(normalizedMetaName)) {
    score += 10;
  }

  return score;
}

async function downloadNapiProjectSubtitle(hash) {
  const endpoint = "http://www.napiprojekt.pl/api/api-napiprojekt3.php";
  const params = new URLSearchParams({
    downloaded_subtitles_id: hash,
    downloaded_subtitles_lang: DEFAULT_LANGUAGE.toUpperCase(),
    downloaded_subtitles_txt: "1",
    client: "NapiProjekt",
    mode: "1",
  });

  const res = await fetch(endpoint, {
    method: "POST",
    headers: { "content-type": "application/x-www-form-urlencoded" },
    body: params.toString(),
  });

  if (!res.ok) {
    throw new Error(`NapiProjekt API returned HTTP ${res.status}`);
  }

  const xml = await res.text();
  const contentMatch = xml.match(/<content>([\s\S]*?)<\/content>/i);
  if (!contentMatch) {
    throw new Error("No <content> node in NapiProjekt response");
  }

  const b64 = contentMatch[1].trim();
  const text = Buffer.from(b64, "base64").toString("utf8");
  return text.replace(/^\uFEFF/, "");
}

function storeSubtitle(text, meta = {}) {
  const id = crypto.randomUUID();
  subtitleCache.set(id, {
    text,
    createdAt: Date.now(),
    meta,
  });
  return id;
}

function cleanupCache() {
  const TTL = 1000 * 60 * 60 * 6; // 6 hours
  const now = Date.now();
  for (const [id, item] of subtitleCache.entries()) {
    if (now - item.createdAt > TTL) subtitleCache.delete(id);
  }
}

/** ---------- addon ---------- */

const manifest = {
  id: "napiprojekt.polish-subtitles",
  version: "1.0.0",
  name: "NapiProjekt Polish Subtitles",
  description: "Best-effort Polish subtitles from NapiProjekt with runtime/release scoring.",
  logo: "./icon.jpg",
  contactEmail: "piotrek1488gmail.com",
  resources: ["subtitles"],
  types: ["movie", "series"],
  idPrefixes: ["tt"],
  catalogs: [],
  behaviorHints: {
    configurable: false,
  },
};

const builder = new addonBuilder(manifest);

builder.defineSubtitlesHandler(async (args) => {
  const { type, id, extra = {} } = args || {};
  if (!id || (type !== "movie" && type !== "series")) {
    return { subtitles: [] };
  }

  const meta = await fetchCinemetaMeta(type, id);
  const filename = extra.filename || "";
  const runtime = getRuntimeSeconds(meta);

  // First try: find a matching NapiProjekt page for this title
  let pageUrl = null;
  try {
    const title = meta?.name || meta?.title || filename || id;
    const year = meta?.year || meta?.releaseInfo?.match?.(/(\d{4})/)?.[1] || null;
    pageUrl = await searchNapiProjectPage(title, year);
  } catch {
    pageUrl = null;
  }

  if (!pageUrl) {
    return { subtitles: [] };
  }

  let pageHtml;
  try {
    pageHtml = await fetchNapiprojektPage(pageUrl);
  } catch {
    return { subtitles: [] };
  }

  const candidates = extractCandidateBlocks(pageHtml, pageUrl)
    .map((c) => ({ ...c, score: scoreCandidate(c, meta, filename) }))
    .filter((c) => c.hash);

  if (!candidates.length) {
    return { subtitles: [] };
  }

  candidates.sort((a, b) => b.score - a.score);

  // Return a small set of the best options, ordered by score.
  const topCandidates = candidates.slice(0, 3);
  const subtitles = [];

  for (const candidate of topCandidates) {
    try {
      const text = await downloadNapiProjectSubtitle(candidate.hash);
      const cacheId = storeSubtitle(text, {
        hash: candidate.hash,
        score: candidate.score,
        pageUrl,
        title: meta?.name || meta?.title || "",
        runtime,
      });

      subtitles.push({
        id: cacheId,
        lang: "pol",
        url: `${PUBLIC_URL}/subtitles/${cacheId}.srt`,
      });
    } catch {
      // skip broken entries
    }
  }

  return {
    subtitles,
    cacheMaxAge: 3600,
    staleRevalidate: 1800,
  };
});

const app = express();

app.use((req, res, next) => {
  res.setHeader("Access-Control-Allow-Origin", "*");
  res.setHeader("Access-Control-Allow-Headers", "*");
  res.setHeader("Access-Control-Allow-Methods", "GET,HEAD,OPTIONS");
  if (req.method === "OPTIONS") {
    return res.status(204).end();
  }
  next();
});

app.get("/subtitles/:id.srt", (req, res) => {
  const item = subtitleCache.get(req.params.id);
  if (!item) {
    return res.status(404).send("Subtitle not found");
  }

  res.setHeader("content-type", "application/x-subrip; charset=utf-8");
  res.send(item.text);
});

app.use("/", getRouter(builder.getInterface()));

setInterval(cleanupCache, 1000 * 60 * 30).unref();

app.listen(PORT, () => {
  console.log(`NapiProjekt addon listening on ${PUBLIC_URL}`);
});
