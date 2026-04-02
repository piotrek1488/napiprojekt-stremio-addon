const result = require('dotenv').config();
if (result.error) {
  console.warn("⚠️ Plik .env nie istnieje, używane będą wartości domyślne");
}
const PORT = process.env.PORT || 7000
const HOSTNAME_URL = process.env.HOSTNAME_URL || "http://localhost"
const PUBLIC_URL = `${HOSTNAME_URL}:${PORT}`
const STREMIO_URL = PUBLIC_URL.replace(/^https?:\/\//, "stremio://")

config = {
  PORT,
  HOSTNAME_URL,
  STREMIO_URL,
  PUBLIC_URL,
  OS_API_KEY: process.env.OS_API_KEY || "",
  ENABLE_OS_FALLBACK: process.env.ENABLE_OS_FALLBACK === "true"
}

function validateConfig() {
  console.log("=== CONFIG ===")
  console.log("HOSTNAME_URL:", config.HOSTNAME_URL)
  console.log("PORT:", config.PORT)
  console.log("PUBLIC_URL:", config.PUBLIC_URL)

  console.log(
    "OpenSubtitles fallback:",
    config.ENABLE_OS_FALLBACK ? "ON ✅" : "OFF ❌"
  )

  if (config.ENABLE_OS_FALLBACK && !config.OS_API_KEY) {
    console.warn("⚠️ Brak OS_API_KEY — fallback nie zadziała")
  }

  console.log("================")
}

module.exports = {
  validateConfig,
  ...config
}