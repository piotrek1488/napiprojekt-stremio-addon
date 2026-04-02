// src/stremio.js
const { findSubtitles } = require("./services/subtitles.service")
const { searchSubtitles: searchOS } = require("./services/opensubtitles.service")
const { ENABLE_OS_FALLBACK, OS_API_KEY } = require("./config")
const StremioSDK = require("stremio-addon-sdk")
const addonBuilder = StremioSDK.addonBuilder 
const getRouter = StremioSDK.getRouter

// Tworzymy builder
const builder = new addonBuilder({
  id: "napiprojekt.stremio",
  version: "1.0.0",
  name: "NapiProjekt",
  description: "Polskie napisy do filmów i seriali",
  catalogs: [],
  resources: ["subtitles"],
  types: ["movie"],
  idPrefixes: ["tt"],
  config: []
})

// Obsługa napisów
builder.defineSubtitlesHandler(async ({ extra }) => {
  const filename = extra?.filename || ""
  let subs = await findSubtitles({ filename })

  const CAN_USE_OS = ENABLE_OS_FALLBACK && OS_API_KEY

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

  return { subtitles: subs }
})

const addonInterface = builder.getInterface()
// Wymuszamy, żeby router widział manifest, jeśli automatycznie go nie wyłapał
module.exports = getRouter({
  manifest: builder.manifest,
  ...addonInterface
})