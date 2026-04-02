const cache = new Map()
function get(k){return cache.get(k)}
function set(k,v){cache.set(k,v)}
module.exports = {get,set}