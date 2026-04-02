const fetch = require("node-fetch")

async function downloadSubtitle(hash) {
  const url = "http://www.napiprojekt.pl/api/api-napiprojekt3.php"

  const params = new URLSearchParams({
    downloaded_subtitles_id: hash,
    downloaded_subtitles_lang: "PL",
    downloaded_subtitles_txt: "1",
    client: "NapiProjekt",
    mode: "1"
  })

  const res = await fetch(url, {
    method: "POST",
    headers: { "content-type": "application/x-www-form-urlencoded" },
    body: params.toString()
  })

  const xml = await res.text()
  const match = xml.match(/<content>([\s\S]*?)<\/content>/)
  if (!match) return null

  return Buffer.from(match[1], "base64").toString("utf8")
}

module.exports = { downloadSubtitle }