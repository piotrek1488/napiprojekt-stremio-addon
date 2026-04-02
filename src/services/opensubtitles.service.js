const fetch = require("node-fetch")

const API_URL = "https://api.opensubtitles.com/api/v1/subtitles"
const API_KEY = process.env.OS_API_KEY

async function searchSubtitles(filename, lang = "pol") {
  const query = encodeURIComponent(filename)
  const url = `${API_URL}?languages=${lang}&query=${query}`

  const res = await fetch(url, {
    headers: {
      "Api-Key": API_KEY,
      "Content-Type": "application/json"
    }
  })

  if (!res.ok) return []

  const data = await res.json()

  return (data.data || []).map(item => ({
    id: item.attributes.files[0].file_id,
    lang: item.attributes.language,
    url: item.attributes.url
  }))
}

module.exports = { searchSubtitles }