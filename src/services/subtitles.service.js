const { searchMovie, parseSubtitles } = require("./napiprojekt.scraper")
const { downloadSubtitle } = require("./napiprojekt.api")
const cache = require("./cache.service")
const { searchSubtitles: searchOS } = require("./opensubtitles.service")

// zmienna środowiskowa do włączania fallbacku
const ENABLE_OS_FALLBACK = process.env.ENABLE_OS_FALLBACK === "true"
const OS_API_KEY = process.env.OS_API_KEY || ""
const CAN_USE_OS = ENABLE_OS_FALLBACK && typeof OS_API_KEY === "string" && OS_API_KEY.length > 0

if (ENABLE_OS_FALLBACK && !OS_API_KEY) {
  console.warn("OpenSubtitles fallback enabled but OS_API_KEY is missing")
}

async function findSubtitles({ filename }) {
  const c = cache.get(filename)
  if (c) return c

  // 1 NapiProjekt
  const page = await searchMovie(filename)
  let subs = []
  if (page) {
    subs = await parseSubtitles(page)
    subs = subs.slice(0, 3).map(s => ({
      id: s.hash,
      lang: "pol",
      url: process.env.PUBLIC_URL + "/sub/" + s.hash
    }))
  }

  // 2 Fallback OpenSubtitles (tylko jeśli CAN_USE_OS = true)
  if (subs.length === 0) {
    console.log("No subtitles from NapiProjekt")
    if (CAN_USE_OS) {
      const osSubs = await searchOS(filename)
      subs = osSubs.map(s => ({
        id: s.id,
        lang: s.lang,
        url: s.url
      }))
    } else {
      console.log("Fallback disabled or missing API key")
    }
  }

  cache.set(filename, subs)
  return subs
}

async function getSubtitle(hash) {
  // jeśli hash wygląda jak NapiProjekt hash, pobierz z API
  if (/^[a-f0-9]{32}$/i.test(hash)) {
    return await downloadSubtitle(hash)
  }
  // w przypadku OpenSubtitles zwracamy URL bezpośrednio (tylko jeśli fallback jest włączony)
  return null
}

module.exports = {
  findSubtitles,
  getSubtitle
}