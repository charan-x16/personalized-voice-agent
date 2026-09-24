class PcmCaptureProcessor extends AudioWorkletProcessor {
  constructor(options) {
    super();
    const processorOptions = options.processorOptions ?? {};
    this.outputSampleRate = processorOptions.outputSampleRate ?? 16000;
    this.frameSize = processorOptions.frameSize ?? 320;
    this.ratio = sampleRate / this.outputSampleRate;
    this.inputSamples = [];
    this.readOffset = 0;
    this.outputSamples = [];
    this.enabled = true;
    this.port.onmessage = (event) => {
      if (event.data?.type === "set-enabled") {
        this.enabled = event.data.enabled === true;
        if (!this.enabled) {
          this.inputSamples = [];
          this.outputSamples = [];
          this.readOffset = 0;
        }
      }
    };
  }

  process(inputs) {
    const channel = inputs[0]?.[0];
    if (!channel?.length || !this.enabled) return true;
    for (let index = 0; index < channel.length; index += 1) {
      this.inputSamples.push(channel[index]);
    }

    while (this.readOffset + this.ratio <= this.inputSamples.length) {
      const start = Math.floor(this.readOffset);
      const end = Math.max(start + 1, Math.floor(this.readOffset + this.ratio));
      let total = 0;
      let count = 0;
      for (let index = start; index < end && index < this.inputSamples.length; index += 1) {
        total += this.inputSamples[index];
        count += 1;
      }
      const sample = Math.max(-1, Math.min(1, count ? total / count : 0));
      this.outputSamples.push(sample < 0 ? sample * 32768 : sample * 32767);
      this.readOffset += this.ratio;

      if (this.outputSamples.length === this.frameSize) {
        const frame = new Int16Array(this.outputSamples);
        this.port.postMessage(frame.buffer, [frame.buffer]);
        this.outputSamples = [];
      }
    }

    const consumed = Math.floor(this.readOffset);
    if (consumed > 0) {
      this.inputSamples.splice(0, consumed);
      this.readOffset -= consumed;
    }
    return true;
  }
}

registerProcessor("pcm-capture-processor", PcmCaptureProcessor);
