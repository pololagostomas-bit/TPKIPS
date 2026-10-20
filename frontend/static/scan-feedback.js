(() => {
  'use strict';

  const MAX_AHEAD = 0.6;
  const GAP = 0.025;
  const SUCCESS = [{offset: 0, duration: 0.09, frequency: 1046.5}];
  const ERROR = [
    {offset: 0, duration: 0.08, frequency: 220},
    {offset: 0.13, duration: 0.08, frequency: 220}
  ];
  let context = null, ready = false, pending = null, nextAt = 0;
  const active = new Set();

  function release(node) {
    active.delete(node);
    try {if (node.oscillator) node.oscillator.disconnect();} catch (_) {}
    try {if (node.gain) node.gain.disconnect();} catch (_) {}
  }

  function clear() {
    nextAt = 0;
    for (const node of active) {
      try {if (node.oscillator) node.oscillator.stop(context.currentTime);} catch (_) {}
      release(node);
    }
  }

  function silence() {
    ready = false;
    clear();
  }

  // Call directly from a user gesture; results never create or resume audio.
  function arm() {
    try {
      if (!context || context.state === 'closed') {
        silence();
        pending = null;
        const AudioContext = window.AudioContext || window.webkitAudioContext;
        if (typeof AudioContext !== 'function') return;
        const created = new AudioContext();
        created.addEventListener('statechange', () => {
          try {
            if (context === created && created.state !== 'running') silence();
          } catch (_) {silence();}
        });
        context = created;
      }
      if (pending) return;
      if (context.state === 'running') {
        ready = true;
        return;
      }
      silence();
      const current = context, attempt = {};
      pending = attempt;
      Promise.resolve(current.resume()).then(() => {
        if (pending !== attempt || context !== current) return;
        pending = null;
        ready = current.state === 'running';
      }, () => {
        if (pending !== attempt || context !== current) return;
        pending = null;
        silence();
      }).catch(() => {
        if (context === current) {
          pending = null;
          silence();
        }
      });
    } catch (_) {
      pending = null;
      silence();
    }
  }

  function play(pattern) {
    try {
      if (!context) return;
      if (context.state !== 'running') {
        silence();
        return;
      }
      if (!ready || pending) return;
      const now = context.currentTime;
      for (const node of active) {
        if (node.end <= now) release(node);
      }
      const start = Math.max(now + 0.005, nextAt);
      const last = pattern[pattern.length - 1];
      const end = start + last.offset + last.duration;
      // Drop whole results on overflow; never defer blocked results for replay.
      if (end > now + MAX_AHEAD) return;
      for (const tone of pattern) {
        const at = start + tone.offset, until = at + tone.duration;
        const node = {oscillator: null, gain: null, end: until};
        active.add(node);
        node.oscillator = context.createOscillator();
        node.gain = context.createGain();
        node.oscillator.onended = () => release(node);
        node.oscillator.type = 'sine';
        node.oscillator.frequency.setValueAtTime(tone.frequency, at);
        const volume = node.gain.gain;
        volume.setValueAtTime(0, at);
        volume.linearRampToValueAtTime(0.08, at + 0.005);
        volume.setValueAtTime(0.08, until - 0.012);
        volume.linearRampToValueAtTime(0, until);
        node.oscillator.connect(node.gain);
        node.gain.connect(context.destination);
        node.oscillator.start(at);
        node.oscillator.stop(until);
      }
      nextAt = end + GAP;
    } catch (_) {clear();}
  }

  window.WmsScanFeedback = {
    arm,
    success() {play(SUCCESS);},
    error() {play(ERROR);}
  };
})();
