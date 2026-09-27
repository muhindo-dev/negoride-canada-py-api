// SOS alarm synthesised with the Web Audio API (no audio file to load or
// block). A two-tone siren that repeats until stop() is called — the Safety
// banner stops it only when every open SOS is acknowledged (spec §8.2.4).
//
// Browsers keep an AudioContext suspended until a user gesture; unlock() is
// wired to the first click/keypress in the console (the login click counts).

let ctx = null;
let timer = null;
let master = null;

const state = { playing: false, beeps: 0, contextState: 'none', startedAt: null };
if (typeof window !== 'undefined') window.__negorideAlarm = state; // read by QA / e2e checks

function ensureCtx() {
  if (!ctx) {
    const AC = window.AudioContext || window.webkitAudioContext;
    if (!AC) return null;
    ctx = new AC();
    master = ctx.createGain();
    master.gain.value = 0.25;
    master.connect(ctx.destination);
  }
  state.contextState = ctx.state;
  return ctx;
}

export function unlockAudio() {
  const c = ensureCtx();
  if (c && c.state === 'suspended') c.resume().then(() => { state.contextState = c.state; }).catch(() => {});
}

function tone(freq, start, dur) {
  const osc = ctx.createOscillator();
  const g = ctx.createGain();
  osc.type = 'sawtooth';
  osc.frequency.setValueAtTime(freq, start);
  osc.frequency.linearRampToValueAtTime(freq * 1.25, start + dur * 0.9);
  g.gain.setValueAtTime(0.0001, start);
  g.gain.exponentialRampToValueAtTime(0.9, start + 0.02);
  g.gain.exponentialRampToValueAtTime(0.0001, start + dur);
  osc.connect(g);
  g.connect(master);
  osc.start(start);
  osc.stop(start + dur + 0.02);
}

function cycle() {
  if (!ctx) return;
  if (ctx.state === 'suspended') ctx.resume().catch(() => {});
  const t = ctx.currentTime + 0.02;
  tone(880, t, 0.28);
  tone(660, t + 0.32, 0.28);
  tone(880, t + 0.64, 0.28);
  state.beeps += 1;
  state.contextState = ctx.state;
}

export function startAlarm() {
  if (state.playing) return;
  if (!ensureCtx()) return;
  state.playing = true;
  state.startedAt = new Date().toISOString();
  cycle();
  timer = window.setInterval(cycle, 1400);
}

export function stopAlarm() {
  state.playing = false;
  if (timer) window.clearInterval(timer);
  timer = null;
}

export function alarmState() {
  return { ...state, contextState: ctx ? ctx.state : 'none' };
}
