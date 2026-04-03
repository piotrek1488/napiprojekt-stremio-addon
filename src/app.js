const express = require("express")
const path = require("path")
const { PORT, PUBLIC_URL, STREMIO_URL } = require("./config")
const stremioRouter = require("./stremio")
const { getSubtitle } = require("./services/subtitles.service")
const { validateConfig } = require("./config")
validateConfig()
const app = express()
const fs = require("fs")
const publicPath = path.resolve(__dirname, "../public")
const indexPath = path.join(publicPath, "index.html")
app.use(express.static(publicPath))

// root redirect na /start
app.get("/", (req, res) => {
  res.redirect("/start")
})

app.get("/start", (req, res) => {
  try {
    let html = fs.readFileSync(indexPath, "utf8")
    html = html
      .replace(/%PUBLIC_URL%/g, PUBLIC_URL)
      .replace(/%STREMIO_URL%/g, STREMIO_URL)
    res.send(html)
  } catch (err) {
    console.error("Błąd wczytywania index.html:", err)
    res.status(500).send("Error loading page")
  }
})

app.use(stremioRouter)
app.get("/sub/:hash", async (req,res)=>{
  const txt = await getSubtitle(req.params.hash)
  if(!txt) return res.status(404).send("not found")
  res.setHeader("content-type","application/x-subrip; charset=utf-8")
  res.send(txt)
})

app.listen(PORT, () => {
  console.log(`Serwer działa na ${PUBLIC_URL}/start`)
  console.log(`Router Stremio dostępny pod /stremio`)
})