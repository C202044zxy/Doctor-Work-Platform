// Real media: composite both video feeds and mix both audio streams into WebM.
// MediaRecorder chunks form ONE file and must be appended in sequence (MDN).
export function createUploadQueue({ start, upload, complete, onStatus = () => {}, delay = ms => new Promise(resolve => setTimeout(resolve, ms)) }) {
  let id, next = 0, running, ended = false, saved = false
  const pending = []
  async function retry(action) {
    for (let attempt = 0; ; attempt++) {
      try { return await action() }
      catch (error) { if (attempt >= 2) throw error; await delay(500 * 2 ** attempt) }
    }
  }
  async function flush() {
    if (running) return running
    running = (async () => {
      try {
        onStatus(ended ? 'Saving replay…' : 'Recording · auto-saving')
        if (!id) id = (await retry(start)).id
        while (pending.length) {
          await retry(() => upload(id, next, pending[0]))
          pending.shift()
          next++
        }
        if (ended && next && !saved) {
          await retry(() => complete(id))
          saved = true
          onStatus('Replay saved')
        }
      } catch (error) {
        onStatus(`Auto-save paused: ${error.message}. Keep this page open and retry.`, true)
      } finally { running = null }
    })()
    return running
  }
  return {
    add(blob) { if (blob.size) pending.push(blob); return flush() },
    async finish() { ended = true; await flush(); if (!saved) await flush(); return saved },
    retry: flush,
    get saved() { return saved },
    get pending() { return pending.length },
  }
}

export function recordingSupported() {
  return typeof MediaRecorder !== 'undefined' && MediaRecorder.isTypeSupported('video/webm')
    && typeof HTMLCanvasElement !== 'undefined' && typeof HTMLCanvasElement.prototype.captureStream === 'function'
}

export function createCallRecorder({ local, remote, audioContext, onChunk, onError, isTest = false }) {
  if (!recordingSupported()) throw new Error('Automatic replay recording is unavailable in this browser. Use desktop Chrome or Edge.')
  const canvas = document.createElement('canvas')
  canvas.width = 1280; canvas.height = 480
  const context = canvas.getContext('2d')
  const mixed = canvas.captureStream(20)
  const destination = audioContext.createMediaStreamDestination()
  const sources = new Map()
  function draw() {
    context.fillStyle = '#142b28'; context.fillRect(0, 0, 1280, 480)
    for (const [index, video] of [local, remote].entries()) {
      const x = index * 640
      if (video?.readyState >= 2 && video.videoWidth) {
        const scale = Math.min(640 / video.videoWidth, 440 / video.videoHeight)
        const w = video.videoWidth * scale, h = video.videoHeight * scale
        context.drawImage(video, x + (640 - w) / 2, (440 - h) / 2, w, h)
      }
      context.fillStyle = '#ffffff'; context.font = '18px sans-serif'
      context.fillText(index ? (isTest ? 'Local test - no patient connected' : 'Other participant') : 'You', x + 20, 465)
      for (const track of video?.srcObject?.getAudioTracks() ?? []) {
        if (!sources.has(track.id)) {
          const source = audioContext.createMediaStreamSource(new MediaStream([track]))
          source.connect(destination)
          sources.set(track.id, source)
        }
      }
    }
  }
  draw()
  destination.stream.getAudioTracks().forEach(track => mixed.addTrack(track))
  const ticker = setInterval(draw, 50)
  const recorder = new MediaRecorder(mixed, { mimeType: 'video/webm', videoBitsPerSecond: 800000, audioBitsPerSecond: 64000 })
  let bytes = 0, resolveStopped, stopped
  const done = new Promise(resolve => { resolveStopped = resolve })
  recorder.ondataavailable = event => {
    if (!event.data.size) return
    bytes += event.data.size
    // Slice oversized browser emissions; reassembly still preserves the exact bytes.
    for (let offset = 0; offset < event.data.size; offset += 4 * 1024 * 1024) {
      onChunk(event.data.slice(offset, offset + 4 * 1024 * 1024, 'video/webm'))
    }
    if (bytes >= 248 * 1024 * 1024 && recorder.state !== 'inactive') {
      onError('Replay recording reached the size limit. The saved portion remains available.')
      recorder.stop()
    }
  }
  recorder.onerror = () => onError('Media recording failed. Already uploaded media will remain available.')
  recorder.onstop = () => {
    clearInterval(ticker)
    sources.forEach(source => source.disconnect())
    mixed.getTracks().forEach(track => track.stop())
    audioContext.close().catch(() => {})
    stopped = true
    resolveStopped()
  }
  recorder.start(5000)
  return {
    done,
    stop() { if (!stopped && recorder.state !== 'inactive') recorder.stop(); return done },
  }
}
