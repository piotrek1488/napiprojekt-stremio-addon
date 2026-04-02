function score(sub, filename="") {
  let s = 0
  if (filename && sub.release && filename.includes(sub.release)) s += 50
  return s
}
module.exports = { score }