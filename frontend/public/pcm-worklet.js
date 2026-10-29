// Collects microphone samples for room notes. Runs only while notes are on.
class PcmCollector extends AudioWorkletProcessor {
  process(inputs) {
    const ch = inputs[0] && inputs[0][0]
    if (ch) this.port.postMessage(ch.slice(0))
    return true
  }
}
registerProcessor('pcm-collector', PcmCollector)
