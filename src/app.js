const express = require("express")
const path = require("path")
const { PORT, PUBLIC_URL, STREMIO_URL } = require("./config")
const stremioRouter = require("./stremio")
const { getSubtitle } = require("./services/subtitles.service")
const { validateConfig } = require("./config")
validateConfig()
const app = express()
const fs = require("fs")

app.get("/", (req, res) => {
  // wczytaj index.html
  let html = fs.readFileSync(path.join(__dirname, "public", "index.html"), "utf8")

  // podmień %PUBLIC_URL% na wartość z config
  html = html
    .replace(/%PUBLIC_URL%/g, PUBLIC_URL)
    .replace(/%STREMIO_URL%/g, STREMIO_URL)

  res.send(html)
})

app.use("/stremio", stremioRouter)
app.get("/sub/:hash", async (req,res)=>{
  const txt = await getSubtitle(req.params.hash)
  if(!txt) return res.status(404).send("not found")
  res.setHeader("content-type","application/x-subrip; charset=utf-8")
  res.send(txt)
})

app.listen(PORT, () => {
  console.log(`Serwer działa na ${PUBLIC_URL}`)
  console.log(`Router Stremio dostępny pod /stremio`)
})