// A same-page loopback: two peer connections wired to each other in memory, so one
// computer can show a connected video pane without a second signed-in participant.
//
// Nothing here touches the signaling socket. That is the point and also the caveat:
// the server refuses an offer when no other connection is in the room
// (`backend/app/calls.py`, "The other participant is offline"), so a self-call cannot
// travel the real path -- it would have to pretend to have a peer. A loopback
// therefore sends no offer, places no call, and leaves no `call_log` row and no audit
// entry. The media is real; the other party is your own camera.

// Candidates can be produced before the far side has a remote description, and
// addIceCandidate rejects in that window. Hold them until the description lands.
function relay(from, to) {
  const held = []
  let open = false
  from.onicecandidate = event => {
    if (!event.candidate) return
    if (!open) { held.push(event.candidate); return }
    // Both peers are in this page and meet on host candidates, so a candidate the
    // far side refuses costs nothing. Never let it surface as an unhandled rejection.
    to.addIceCandidate(event.candidate).catch(() => {})
  }
  return () => {
    open = true
    for (const candidate of held.splice(0)) to.addIceCandidate(candidate).catch(() => {})
  }
}

// Resolve only once the connection is really up, so a caller that awaits this knows
// the picture it is about to show is live rather than merely requested.
function connected(peer) {
  if (peer.connectionState === 'connected') return Promise.resolve()
  return new Promise((resolve, reject) => {
    const settle = () => {
      if (!['connected', 'failed', 'closed'].includes(peer.connectionState)) return
      peer.removeEventListener('connectionstatechange', settle)
      if (peer.connectionState === 'connected') resolve()
      else reject(new Error('The loopback connection failed.'))
    }
    peer.addEventListener('connectionstatechange', settle)
    // `connectionState` can move between the read above and the listener being set.
    settle()
  })
}

export async function connectLoopback(stream, {
  Peer = globalThis.RTCPeerConnection,
  Stream = globalThis.MediaStream,
} = {}) {
  if (!Peer) throw new Error('This browser does not support WebRTC.')
  const outgoing = new Peer({ iceServers: [] })
  const incoming = new Peer({ iceServers: [] })
  const remote = new Stream()
  const close = () => { outgoing.close(); incoming.close() }
  try {
    stream.getTracks().forEach(track => outgoing.addTrack(track, stream))
    incoming.ontrack = event => remote.addTrack(event.track)
    const releaseOutgoing = relay(outgoing, incoming)
    const releaseIncoming = relay(incoming, outgoing)
    const offer = await outgoing.createOffer()
    await outgoing.setLocalDescription(offer)
    await incoming.setRemoteDescription(offer)
    releaseOutgoing()
    const answer = await incoming.createAnswer()
    await incoming.setLocalDescription(answer)
    await outgoing.setRemoteDescription(answer)
    releaseIncoming()
    await connected(outgoing)
  } catch (error) {
    // A half-wired pair would keep the camera indicator on with no way to reach it.
    close()
    throw error
  }
  return { remote, close }
}
