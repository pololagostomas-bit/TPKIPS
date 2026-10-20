const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const filename = path.join(__dirname, '../frontend/static/scan-feedback.js');
const source = fs.existsSync(filename) ? fs.readFileSync(filename, 'utf8') : '';
const flush = () => new Promise(resolve => setImmediate(resolve));

function deferred() {
  let resolve, reject;
  const promise = new Promise((yes, no) => {resolve = yes; reject = no;});
  return {promise, resolve, reject};
}

function fixture(options = {}) {
  const contexts = [];
  const faults = new Set();
  let constructions = 0;
  function check(operation) {
    if (faults.has(operation)) throw new Error('Unavailable: ' + operation);
  }
  function parameter(name) {
    return {
      events: [],
      setValueAtTime(value, time) {check(name); this.events.push({value, time});},
      linearRampToValueAtTime(value, time) {check(name); this.events.push({value, time});}
    };
  }
  class AudioContext {
    constructor() {
      constructions++;
      if (options.constructorError) throw new Error('Audio blocked');
      this.state = options.state || 'running';
      this.currentTime = 10;
      this.destination = {};
      this.oscillators = [];
      this.gains = [];
      this.listeners = [];
      this.resumeCalls = 0;
      contexts.push(this);
    }
    addEventListener(name, listener) {
      assert.equal(name, 'statechange');
      check('addEventListener');
      this.listeners.push(listener);
    }
    transition(state) {
      this.state = state;
      for (const listener of this.listeners) listener();
    }
    resume() {
      this.resumeCalls++;
      check('resume');
      if (options.resume) return options.resume(this);
      this.transition('running');
      return Promise.resolve();
    }
    createOscillator() {
      check('createOscillator');
      const oscillator = {
        frequency: parameter('frequency'), type: '', starts: [], stops: [], connections: [],
        connect(target) {check('oscillator.connect'); this.connections.push(target);},
        disconnect() {check('oscillator.disconnect'); this.disconnected = true;},
        start(time) {check('start'); this.starts.push(time);},
        stop(time) {check('stop'); this.stops.push(time);},
        finish() {if (this.onended) this.onended();}
      };
      this.oscillators.push(oscillator);
      return oscillator;
    }
    createGain() {
      check('createGain');
      const gain = {
        gain: parameter('gain'), connections: [],
        connect(target) {check('gain.connect'); this.connections.push(target);},
        disconnect() {check('gain.disconnect'); this.disconnected = true;}
      };
      this.gains.push(gain);
      return gain;
    }
  }
  const window = {};
  if (!options.unsupported) window[options.prefixed ? 'webkitAudioContext' : 'AudioContext'] = AudioContext;
  if (options.getterError) Object.defineProperty(window, 'AudioContext', {
    get() {throw new Error('Audio API blocked');}
  });
  vm.runInNewContext(source, {window}, {filename});
  const api = window.WmsScanFeedback;
  assert.ok(api, 'scan-feedback.js must expose window.WmsScanFeedback');
  return {api, contexts, faults, constructions: () => constructions};
}

function sounded(context) {
  return context.oscillators.filter(oscillator => oscillator.starts.length);
}

test('load and results before arm never create a context or play', () => {
  const {api, contexts} = fixture();
  assert.deepEqual(Object.keys(api).sort(), ['arm', 'error', 'success']);
  for (let i = 0; i < 20; i++) {api.success(); api.error();}
  assert.equal(contexts.length, 0);
});

test('arm creates one context without a tone and reuses it', () => {
  const {api, contexts} = fixture();
  api.arm(); api.arm();
  assert.equal(contexts.length, 1);
  assert.equal(contexts[0].resumeCalls, 0);
  assert.equal(sounded(contexts[0]).length, 0);
});

test('success is one short high tone; error is two separated lower tones', () => {
  const {api, contexts} = fixture();
  api.arm(); api.success(); api.error();
  const context = contexts[0], tones = sounded(context);
  assert.equal(tones.length, 3);
  const [success, firstError, secondError] = tones;
  const pitch = oscillator => oscillator.frequency.events[0].value;
  assert.ok(pitch(success) >= 800);
  assert.ok(pitch(firstError) <= 400 && pitch(firstError) > 0);
  assert.equal(pitch(firstError), pitch(secondError));
  assert.ok(firstError.starts[0] > success.stops[0]);
  assert.ok(secondError.starts[0] > firstError.stops[0]);
  for (const [index, oscillator] of tones.entries()) {
    assert.equal(oscillator.type, 'sine');
    assert.ok(oscillator.starts[0] >= context.currentTime);
    assert.ok(oscillator.stops[0] - oscillator.starts[0] <= 0.15);
    assert.equal(oscillator.connections[0], context.gains[index]);
    assert.equal(context.gains[index].connections[0], context.destination);
    const envelope = context.gains[index].gain.events;
    assert.equal(envelope[0].value, 0);
    assert.equal(envelope.at(-1).value, 0);
    assert.ok(envelope.some(event => event.value > 0 && event.value <= 0.15));
    assert.ok(envelope.every(event => event.time >= oscillator.starts[0] && event.time <= oscillator.stops[0]));
  }
});

test('arm resumes synchronously in the gesture; pending results are discarded', async () => {
  const unlock = deferred();
  const {api, contexts} = fixture({state: 'suspended', resume: () => unlock.promise});
  api.arm();
  const context = contexts[0];
  assert.equal(context.resumeCalls, 1);
  api.arm(); api.success(); api.error();
  assert.equal(context.resumeCalls, 1);
  assert.equal(sounded(context).length, 0);
  context.transition('running');
  api.success();
  assert.equal(sounded(context).length, 0, 'No playback before unlock settles');
  unlock.resolve(); await flush();
  assert.equal(sounded(context).length, 0, 'Unlock cannot replay old results');
  api.success();
  assert.equal(sounded(context).length, 1);
});

test('a fulfilled resume that is still suspended does not enable playback', async () => {
  const {api, contexts} = fixture({state: 'suspended', resume: () => Promise.resolve()});
  api.arm(); await flush();
  api.success(); api.error();
  contexts[0].transition('running');
  api.success();
  assert.equal(sounded(contexts[0]).length, 0);
  api.arm(); api.success();
  assert.equal(sounded(contexts[0]).length, 1);
});

test('resume rejection is contained and a later arm can retry without stale sounds', async () => {
  let blocked = true;
  const {api, contexts} = fixture({state: 'suspended', resume(context) {
    if (blocked) return Promise.reject(new Error('Gesture required'));
    context.transition('running'); return Promise.resolve();
  }});
  assert.doesNotThrow(() => api.arm());
  api.error(); await flush();
  const context = contexts[0];
  assert.equal(sounded(context).length, 0);
  blocked = false;
  api.arm(); api.success(); await flush();
  assert.equal(sounded(context).length, 0);
  api.error();
  assert.equal(sounded(context).length, 2);
  assert.equal(context.resumeCalls, 2);
});

test('results never resume a suspended context on their own', () => {
  const {api, contexts} = fixture();
  api.arm();
  const context = contexts[0];
  context.transition('suspended');
  api.success(); api.error();
  assert.equal(context.resumeCalls, 0);
  assert.equal(sounded(context).length, 0);
});

test('suspension cancels queued tones and rearm starts a fresh timeline', async () => {
  const {api, contexts} = fixture();
  api.arm(); api.error(); api.success();
  const context = contexts[0], old = sounded(context).slice();
  context.transition('suspended');
  for (const oscillator of old) {
    assert.equal(oscillator.stops.at(-1), context.currentTime, 'Cancel before frozen audio time advances');
    assert.equal(oscillator.disconnected, true);
  }
  api.error();
  context.transition('running');
  api.success();
  assert.equal(sounded(context).length, old.length);
  api.arm(); await flush(); api.success();
  const latest = sounded(context).at(-1);
  assert.ok(latest.starts[0] <= context.currentTime + 0.02);
  assert.equal(sounded(context).length, old.length + 1);
});

test('results detect suspension even before its statechange event arrives', async () => {
  const {api, contexts} = fixture();
  api.arm(); api.error();
  const context = contexts[0], old = sounded(context).slice();
  context.state = 'suspended';
  api.success();
  assert.ok(old.every(oscillator => oscillator.disconnected));
  api.arm(); await flush();
  assert.equal(sounded(context).length, 2);
  api.success();
  assert.equal(sounded(context).length, 3);
  assert.ok(sounded(context).at(-1).starts[0] <= context.currentTime + 0.02);
});

test('closed contexts are recreated only on the next arm', () => {
  const {api, contexts} = fixture();
  api.arm(); api.success();
  contexts[0].transition('closed');
  api.success(); api.error();
  assert.equal(contexts.length, 1);
  api.arm();
  assert.equal(contexts.length, 2);
  assert.equal(sounded(contexts[1]).length, 0);
  api.error();
  assert.equal(sounded(contexts[1]).length, 2);
});

test('late unlock completion from a closed context cannot arm its replacement', async () => {
  const unlocks = [deferred(), deferred()];
  let attempt = 0;
  const {api, contexts} = fixture({state: 'suspended', resume: () => unlocks[attempt++].promise});
  api.arm(); contexts[0].transition('closed'); api.arm();
  assert.equal(contexts.length, 2);
  contexts[1].transition('running');
  unlocks[0].resolve(); await flush(); api.success();
  assert.equal(sounded(contexts[1]).length, 0);
  unlocks[1].resolve(); await flush(); api.success();
  assert.equal(sounded(contexts[1]).length, 1);
});

test('rapid mixed results serialize complete patterns within 600 ms and drop overflow', () => {
  const {api, contexts} = fixture();
  api.arm();
  for (let i = 0; i < 1000; i++) {api.success(); api.error();}
  const context = contexts[0], tones = sounded(context);
  assert.ok(tones.length >= 3 && tones.length <= 12, 'Bound both delay and node allocation');
  assert.equal(tones.filter(oscillator => oscillator.frequency.events[0].value <= 400).length % 2, 0);
  for (const [index, oscillator] of tones.entries()) {
    assert.ok(oscillator.stops[0] <= context.currentTime + 0.6 + 1e-9);
    if (index) assert.ok(oscillator.starts[0] > tones[index - 1].stops[0]);
  }
  for (const oscillator of tones) oscillator.finish();
  context.currentTime += 5;
  api.success();
  assert.equal(sounded(context).length, tones.length + 1);
  assert.ok(sounded(context).at(-1).starts[0] <= context.currentTime + 0.02);
});

test('completed tones disconnect both audio nodes', () => {
  const {api, contexts} = fixture();
  api.arm(); api.error();
  const context = contexts[0];
  for (const oscillator of sounded(context)) oscillator.finish();
  assert.ok(context.oscillators.every(oscillator => oscillator.disconnected));
  assert.ok(context.gains.every(gain => gain.disconnected));
});

for (const options of [{unsupported: true}, {constructorError: true}, {getterError: true}]) {
  test('unavailable audio stays silent: ' + Object.keys(options)[0], async () => {
    const {api, contexts, constructions} = fixture(options);
    assert.equal(constructions(), 0);
    for (let i = 0; i < 2; i++) {
      assert.doesNotThrow(() => {api.arm(); api.success(); api.error();});
      await flush();
    }
    assert.equal(contexts.length, 0);
  });
}

test('webkitAudioContext fallback can produce feedback after arm', () => {
  const {api, contexts} = fixture({prefixed: true});
  api.arm(); api.success();
  assert.equal(sounded(contexts[0]).length, 1);
});

test('synchronous resume failures cannot escape and a later gesture can retry', async () => {
  const {api, contexts, faults} = fixture({state: 'suspended'});
  faults.add('resume');
  assert.doesNotThrow(() => api.arm());
  api.success(); api.error();
  assert.equal(sounded(contexts[0]).length, 0);
  faults.clear(); api.arm(); await flush(); api.success();
  assert.equal(sounded(contexts[0]).length, 1);
});

for (const operation of ['createOscillator', 'createGain', 'frequency', 'gain',
  'oscillator.connect', 'gain.connect', 'start', 'stop']) {
  test('audio node failure is contained and recoverable: ' + operation, () => {
    const {api, contexts, faults} = fixture();
    api.arm(); faults.add(operation);
    assert.doesNotThrow(() => {api.success(); api.error();});
    const context = contexts[0], previous = sounded(context).length;
    assert.ok(context.oscillators.every(oscillator => oscillator.disconnected));
    faults.clear(); api.success();
    assert.equal(sounded(context).length, previous + 1);
    assert.ok(sounded(context).at(-1).starts[0] <= context.currentTime + 0.02);
  });
}

test('cleanup exceptions never escape statechange or ended callbacks', () => {
  const {api, contexts, faults} = fixture();
  api.arm(); api.error();
  faults.add('oscillator.disconnect'); faults.add('gain.disconnect'); faults.add('stop');
  const context = contexts[0];
  assert.doesNotThrow(() => context.transition('suspended'));
  for (const oscillator of sounded(context)) assert.doesNotThrow(() => oscillator.finish());
});
