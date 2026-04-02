config = {
  PORT: process.env.PORT || 7000,
  PUBLIC_URL: process.env.PUBLIC_URL || "http://localhost:7000",
  OS_API_KEY: process.env.OS_API_KEY || "",
  ENABLE_OS_FALLBACK: process.env.ENABLE_OS_FALLBACK === "true"
}

function validateConfig() {
  console.log("=== CONFIG ===")

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