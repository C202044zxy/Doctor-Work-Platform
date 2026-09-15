// T12 签收标准 2: the export's filename comes from the server, not from the client.
//
// `Content-Disposition` can carry the name two ways and which one is usable depends
// on the client: a bare `filename` cannot hold non-ASCII, and a bare `filename*`
// (RFC 5987) is ignored by older parsers. The backend sends both, so both are read
// -- `filename*` first, because when the two disagree the encoded one is the one
// that survived encoding intact.
//
// This lives in its own module rather than inside `client.js` because that module
// touches the browser at import time and a pure function is the part worth testing.
export function filenameFromDisposition(header) {
  if (!header) return null

  const encoded = /filename\*=\s*UTF-8''([^;]+)/i.exec(header)
  if (encoded) {
    try {
      return decodeURIComponent(encoded[1].trim().replace(/^"|"$/g, ''))
    } catch {
      // A malformed escape is not worth failing the download over -- fall through
      // and try the plain parameter, which may still be readable.
    }
  }

  const plain = /filename=\s*(?:"([^"]*)"|([^;]+))/i.exec(header)
  if (plain) return (plain[1] ?? plain[2]).trim()

  return null
}
