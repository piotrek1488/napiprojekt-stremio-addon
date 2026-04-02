const fetch = require("node-fetch")

async function fetchWithRetry(url, options = {}, retries = 3) {
  try {
    const res = await fetch(url, options)
    if (!res.ok) throw new Error("HTTP " + res.status)
    return res
  } catch (e) {
    if (retries > 0) return fetchWithRetry(url, options, retries - 1)
    throw e
  }
}

module.exports = { fetchWithRetry }