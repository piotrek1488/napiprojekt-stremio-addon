const result = require('dotenv').config();
if (result.error) {
  console.warn("⚠️ Plik .env nie istnieje, używane będą wartości domyślne");
}
const isProd = process.env.NODE_ENV === "production";
const PORT = process.env.PORT || 7000
const HOSTNAME_URL = process.env.HOSTNAME_URL || "http://localhost"
// PUBLIC_URL bierze pod uwagę port tylko lokalnie
const PUBLIC_URL = isProd
  ? HOSTNAME_URL                 // produkcja – nie dodajemy portu
  : `${HOSTNAME_URL}:${PORT}`;   // lokalnie – dorzuć port

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