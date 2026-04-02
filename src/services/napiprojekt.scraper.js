const cheerio = require("cheerio")
const { fetchWithRetry } = require("../utils/http")

async function searchMovie(query) {
  const url = `https://www.napiprojekt.pl/ajax/search_catalog.php?query=${encodeURIComponent(query)}`
  const res = await fetchWithRetry(url)
  const html = await res.text()

  const $ = cheerio.load(html)
  let link = null

  $("a").each((_, el) => {
    const href = $(el).attr("href")
    if (href && href.includes("/napisy/")) {
      link = "https://www.napiprojekt.pl" + href
    }
  })

  return link
}

async function parseSubtitles(pageUrl) {
  const res = await fetchWithRetry(pageUrl)
  const html = await res.text()
  const $ = cheerio.load(html)

  const subs = []

  $("tr").each((_, row) => {
    const text = $(row).text()

    const hashMatch = text.match(/napiprojekt:([a-f0-9]{32})/i)
    if (!hashMatch) return

    subs.push({
      hash: hashMatch[1],
      release: text,
      duration: 0
    })
  })

  return subs
}

module.exports = { searchMovie, parseSubtitles }