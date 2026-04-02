const express = require("express")
const { PORT, PUBLIC_URL } = require("./config")
const stremioRouter = require("./stremio")
const { getSubtitle } = require("./services/subtitles.service")
const { validateConfig } = require("./config")
validateConfig()

const app = express()

app.use("/", stremioRouter)

app.get("/sub/:hash", async (req,res)=>{
  const txt = await getSubtitle(req.params.hash)
  if(!txt) return res.status(404).send("not found")
  res.setHeader("content-type","application/x-subrip; charset=utf-8")
  res.send(txt)
})

app.listen(PORT, () => {
  console.log(`Serwer działa na ${PUBLIC_URL}`)
  // console.log(`Router Stremio dostępny pod /`)
})