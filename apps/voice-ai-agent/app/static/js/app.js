"use strict";
/* =========================================================================
 * Divan — Əfsanələr Şurası — frontend logic.
 *
 * Talks to the REAL FastAPI backend only:
 *   POST /chat            {message, thread_id}        -> ChatResponse
 *   POST /chat/resume     {thread_id, decision, text?} -> ChatResponse
 *   POST /voice           multipart {file, thread_id}  -> VoiceResponse
 *   POST /voice/resume    form {thread_id, decision, text?} -> VoiceResponse
 *   POST /feedback        {turn_id, thread_id, kind, text?, advisor?}
 *   GET  /feedback/stats  -> {up, down, correction, total}
 *
 * No mock data anywhere: every message, advisor consultation, audio clip and
 * stat shown here is whatever the live LangGraph council + ElevenLabs/OpenAI
 * TTS actually returned for this session.
 * ========================================================================= */

/* -- roster metadata mirrored verbatim from app/prompts/divan.py, used only
   for display labels (chip names, roster legend) — never for routing logic,
   which is entirely server-side. */
const ROSTER = {
  nesreddin: { name: "Molla Nəsrəddin", domain: "gündəlik problemlər, yumor və zəka, gözlənilməz baxış bucağı" },
  koroglu: { name: "Koroğlu", domain: "cəsarət, qətiyyət, risk, haqsızlığa qarşı mübarizə" },
  simurg: { name: "Simurğ", domain: "dərin həyat sualları, uzunmüddətli perspektiv, mənəvi müdriklik" },
  nesimi: { name: "Nəsimi", domain: "özünəinam, mənəvi kimlik, tənqid qarşısında dözüm" },
  dedeqorqud: { name: "Dədə Qorqud", domain: "ailə və icma, nəsihət, həyat keçidlərində istiqamət" },
  nizami: { name: "Nizami Gəncəvi", domain: "sevgi, ədalət, əxlaqi seçimlər, düzgün qərar" },
};
const ICONS = {
  up: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M14 9V5a3 3 0 0 0-3-3L7 11v11h11.28a2 2 0 0 0 2-1.7l1.38-9a2 2 0 0 0-2-2.3zM7 22H4a2 2 0 0 1-2-2v-7a2 2 0 0 1 2-2h3"/></svg>',
  down: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M10 15v4a3 3 0 0 0 3 3l4-9V2H5.72a2 2 0 0 0-2 1.7l-1.38 9a2 2 0 0 0 2 2.3zM17 2h2.67A2.31 2.31 0 0 1 22 4v7a2.31 2.31 0 0 1-2.33 2H17"/></svg>',
  pencil: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M17 3a2.85 2.83 0 1 1 4 4L7.5 20.5 2 22l1.5-5.5Z"/></svg>',
  play: '<svg viewBox="0 0 24 24" fill="currentColor" stroke="none"><polygon points="5 3 19 12 5 21 5 3"/></svg>',
  mic: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 1a3 3 0 0 0-3 3v8a3 3 0 0 0 6 0V4a3 3 0 0 0-3-3z"/><path d="M19 10v2a7 7 0 0 1-14 0v-2"/><line x1="12" y1="19" x2="12" y2="23"/><line x1="8" y1="23" x2="16" y2="23"/></svg>',
  type: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="4 7 4 4 20 4 20 7"/><line x1="9" y1="20" x2="15" y2="20"/><line x1="12" y1="4" x2="12" y2="20"/></svg>',
  clock: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"/><polyline points="12 6 12 12 16 14"/></svg>',
  hash: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><line x1="4" y1="9" x2="20" y2="9"/><line x1="4" y1="15" x2="20" y2="15"/><line x1="10" y1="3" x2="8" y2="21"/><line x1="16" y1="3" x2="14" y2="21"/></svg>',
};

/* ---------------------------------------------------------------------- *
 * State
 * ---------------------------------------------------------------------- */

/* ---------------------------------------------------------------------- *
 * Client-side error telemetry — every uncaught browser error is beaconed to
 * POST /client-log, so frontend failures show up in the backend logs
 * instead of dying silently in the visitor's console.
 * ---------------------------------------------------------------------- */

function reportClientError(kind, message, source) {
  try {
    const body = JSON.stringify({
      kind,
      message: String(message).slice(0, 300),
      source: String(source || "").slice(0, 150),
      url: location.href,
      ua: navigator.userAgent.slice(0, 120),
    });
    if (navigator.sendBeacon) {
      navigator.sendBeacon("/client-log", new Blob([body], { type: "application/json" }));
    } else {
      fetch("/client-log", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body,
        keepalive: true,
      }).catch(() => {});
    }
  } catch {
    /* telemetry must never break the page */
  }
}
window.addEventListener("error", (e) =>
  reportClientError("error", e.message, (e.filename || "") + ":" + (e.lineno || ""))
);
window.addEventListener("unhandledrejection", (e) =>
  reportClientError("unhandledrejection", (e.reason && e.reason.message) || e.reason)
);

const state = {
  threadId: "web-" + Math.random().toString(36).slice(2, 10),
  // { modality: 'text'|'voice' } while a turn is parked at approval_gate on
  // the server, awaiting /chat/resume or /voice/resume; null otherwise. Also
  // guards against feeding a new message into a thread whose previous turn
  // is still interrupted (see app/graph/builder.py get_pending's docstring).
  pending: null,
};

/* ---------------------------------------------------------------------- *
 * DOM refs
 * ---------------------------------------------------------------------- */

const $log = document.getElementById("log");
const $form = document.getElementById("form");
const $input = document.getElementById("input");
const $chamber = document.getElementById("chamber");
const $fbstats = document.getElementById("fbstats");
const $toasts = document.getElementById("toasts");
const $micBtn = document.getElementById("mic-btn");
const $micLabel = document.getElementById("mic-label");
const $recTimer = document.getElementById("rec-timer");
const $voiceError = document.getElementById("voice-error");

/* ---------------------------------------------------------------------- *
 * API — thin wrappers, exact field names per app/models/schemas.py
 * ---------------------------------------------------------------------- */

async function safeErrText(res) {
  try {
    const j = await res.json();
    return j.detail || res.statusText || ("HTTP " + res.status);
  } catch {
    return res.statusText || "HTTP " + res.status;
  }
}

const api = {
  async chat(message) {
    const res = await fetch("/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ message, thread_id: state.threadId }),
    });
    if (!res.ok) throw new Error(await safeErrText(res));
    return res.json();
  },
  async chatResume(decision, text) {
    const res = await fetch("/chat/resume", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ thread_id: state.threadId, decision, text: text || null }),
    });
    if (!res.ok) throw new Error(await safeErrText(res));
    return res.json();
  },
  async voice(formData) {
    const res = await fetch("/voice", { method: "POST", body: formData });
    if (!res.ok) throw new Error(await safeErrText(res));
    return res.json();
  },
  async voiceResume(decision, text) {
    const fd = new FormData();
    fd.append("thread_id", state.threadId);
    fd.append("decision", decision);
    if (text) fd.append("text", text);
    const res = await fetch("/voice/resume", { method: "POST", body: fd });
    if (!res.ok) throw new Error(await safeErrText(res));
    return res.json();
  },
  async feedback(payload) {
    const res = await fetch("/feedback", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    if (!res.ok) throw new Error(await safeErrText(res));
    return res.json();
  },
  async feedbackStats() {
    const res = await fetch("/feedback/stats");
    if (!res.ok) throw new Error(await safeErrText(res));
    return res.json();
  },
  async voicelabNext(skip) {
    const url = skip == null ? "/voicelab/next" : "/voicelab/next?skip=" + skip;
    const res = await fetch(url);
    if (!res.ok) throw new Error(await safeErrText(res));
    return res.json();
  },
  async voicelabSample(formData) {
    const res = await fetch("/voicelab/sample", { method: "POST", body: formData });
    if (!res.ok) throw new Error(await safeErrText(res));
    return res.json();
  },
};

/* ---------------------------------------------------------------------- *
 * Toasts
 * ---------------------------------------------------------------------- */

function toast(message, type) {
  const el = document.createElement("div");
  el.className = "toast " + (type || "ok");
  el.textContent = message;
  $toasts.appendChild(el);
  setTimeout(() => {
    el.classList.add("leaving");
    setTimeout(() => el.remove(), 220);
  }, 3800);
}

/* ---------------------------------------------------------------------- *
 * "Nə baş verir?" steps panel
 * ---------------------------------------------------------------------- */

function setSteps(map) {
  Object.entries(map).forEach(([name, s]) => {
    const el = document.querySelector('.step[data-step="' + name + '"]');
    if (!el) return;
    el.classList.remove("done", "live");
    if (s) el.classList.add(s);
  });
}
function resetSteps() {
  document.querySelectorAll(".step").forEach((s) => s.classList.remove("done", "live"));
}

/* ---------------------------------------------------------------------- *
 * Council chamber — SVG hub + 6 seats, animated beams
 * ---------------------------------------------------------------------- */

// Bumped on every new turn so stale setTimeout callbacks from a reveal that
// belongs to a previous, already-cleared turn can recognize themselves as
// stale and no-op instead of re-lighting seats on top of the new turn.
let chamberTurnSeq = 0;

function resetChamber() {
  chamberTurnSeq++;
  $chamber.classList.remove("thinking");
  $chamber.querySelectorAll(".beam").forEach((b) => b.classList.remove("lit"));
  $chamber.querySelectorAll(".seat").forEach((s) => s.classList.remove("active", "speaking"));
  const hub = $chamber.querySelector(".hub");
  if (hub) hub.classList.remove("speaking");
}

function chamberThinking(on) {
  $chamber.classList.toggle("thinking", !!on);
}

/** Reveal the real, already-known speaking order with a short stagger — this
 * is a client-side reveal choreography of a result we already have in hand
 * (the backend returns `consulted` / `segments` in actual speaking order),
 * never a guess about who is *about* to be picked. */
function revealConsulted(keys) {
  chamberThinking(false);
  const seq = chamberTurnSeq;
  (keys || []).forEach((key, i) => {
    setTimeout(() => {
      if (seq !== chamberTurnSeq) return; // a newer turn has already reset the chamber
      const beam = $chamber.querySelector(".beam-" + key);
      const seat = $chamber.querySelector(".seat." + key);
      if (beam) beam.classList.add("lit");
      if (seat) seat.classList.add("active");
    }, i * 260);
  });
}

function highlightSpeaking(advisorKey) {
  $chamber.querySelectorAll(".seat.speaking").forEach((s) => s.classList.remove("speaking"));
  const hub = $chamber.querySelector(".hub");
  if (hub) hub.classList.remove("speaking");
  if (advisorKey) {
    const seat = $chamber.querySelector(".seat." + advisorKey);
    if (seat) seat.classList.add("speaking", "active");
    const beam = $chamber.querySelector(".beam-" + advisorKey);
    if (beam) beam.classList.add("lit");
  } else if (hub) {
    hub.classList.add("speaking");
  }
}
function clearSpeaking() {
  $chamber.querySelectorAll(".seat.speaking").forEach((s) => s.classList.remove("speaking"));
  const hub = $chamber.querySelector(".hub");
  if (hub) hub.classList.remove("speaking");
}

/* ---------------------------------------------------------------------- *
 * Conversation log — turn builders
 * ---------------------------------------------------------------------- */

function startTurn(userText, opts) {
  opts = opts || {};
  const turn = document.createElement("div");
  turn.className = "turn";

  const bubble = document.createElement("div");
  bubble.className = "msg user";
  if (opts.via === "voice") {
    const via = document.createElement("div");
    via.className = "via";
    via.innerHTML = ICONS.mic;
    via.appendChild(document.createTextNode(" SƏS"));
    bubble.appendChild(via);
  }
  const textEl = document.createElement("span");
  textEl.textContent = userText;
  bubble.appendChild(textEl);
  turn.appendChild(bubble);
  turn._userTextEl = textEl;

  $log.appendChild(turn);
  $log.scrollTop = $log.scrollHeight;
  return turn;
}

function updateTurnUserText(turn, text) {
  if (turn._userTextEl) turn._userTextEl.textContent = text;
}

function appendBotBubble(turn, text, cls) {
  const bubble = document.createElement("div");
  bubble.className = "msg " + cls;
  bubble.textContent = text;
  turn.appendChild(bubble);
  $log.scrollTop = $log.scrollHeight;
  return bubble;
}

function appendChips(turn, consultedKeys) {
  if (!consultedKeys || !consultedKeys.length) return;
  const row = document.createElement("div");
  row.className = "chips";
  consultedKeys.forEach((key) => {
    const info = ROSTER[key];
    const chip = document.createElement("span");
    chip.className = "chip " + key;
    const dot = document.createElement("span");
    dot.className = "dot";
    chip.appendChild(dot);
    chip.appendChild(document.createTextNode(info ? info.name : key));
    row.appendChild(chip);
  });
  turn.appendChild(row);
  $log.scrollTop = $log.scrollHeight;
}

/* -- voice segment player: one real audio clip per council member who
   actually spoke, played in the order the backend returned them (speaking
   order), highlighting that advisor's seat in the chamber while it plays. */
let _activeStop = null;

function b64ToBlobUrl(b64, mime) {
  const bin = atob(b64);
  const bytes = new Uint8Array(bin.length);
  for (let i = 0; i < bin.length; i++) bytes[i] = bin.charCodeAt(i);
  return URL.createObjectURL(new Blob([bytes], { type: mime || "audio/ogg" }));
}

function createSegmentPlayer(segments) {
  const audio = new Audio();
  const urls = new Array(segments.length).fill(null);
  let stopped = false;

  function urlFor(i) {
    if (!urls[i]) urls[i] = b64ToBlobUrl(segments[i].audio_base64, segments[i].audio_mime);
    return urls[i];
  }

  function arm() {
    stopped = false;
    _activeStop = () => {
      stopped = true;
      audio.pause();
      clearSpeaking();
    };
  }

  function playIndex(i, onSeg, onDone) {
    if (stopped || i >= segments.length) {
      clearSpeaking();
      if (onDone) onDone();
      return;
    }
    highlightSpeaking(segments[i].advisor);
    if (onSeg) onSeg(i);
    audio.src = urlFor(i);
    audio.play().catch(() => {});
    audio.onended = () => playIndex(i + 1, onSeg, onDone);
  }

  return {
    playAll(onSeg, onDone) {
      if (_activeStop) _activeStop();
      arm();
      playIndex(0, onSeg, onDone);
    },
    playOnly(i, onDone) {
      if (_activeStop) _activeStop();
      arm();
      highlightSpeaking(segments[i].advisor);
      audio.src = urlFor(i);
      audio.play().catch(() => {});
      audio.onended = () => {
        clearSpeaking();
        if (onDone) onDone();
      };
    },
  };
}

function appendPlayer(turn, segments) {
  if (!segments || !segments.length) return;
  const wrap = document.createElement("div");
  wrap.className = "player";

  const head = document.createElement("div");
  head.className = "player-head";
  const playBtn = document.createElement("button");
  playBtn.type = "button";
  playBtn.className = "btn small";
  playBtn.innerHTML = ICONS.play;
  playBtn.appendChild(document.createTextNode(" Şuranı dinlə"));
  const lbl = document.createElement("span");
  lbl.className = "lbl";
  lbl.textContent = segments.length + " nitq parçası — öz səsləri ilə, sırayla";
  head.append(playBtn, lbl);

  const seq = document.createElement("div");
  seq.className = "player-seq";
  const ctrl = createSegmentPlayer(segments);
  const segEls = segments.map((s, i) => {
    const el = document.createElement("button");
    el.type = "button";
    el.className = "seg" + (s.advisor ? " " + s.advisor : "");
    const dot = document.createElement("span");
    dot.className = "dot";
    el.appendChild(dot);
    el.appendChild(document.createTextNode(s.name));
    el.title = s.text;
    el.addEventListener("click", () => {
      // A lone segment replay always wins over an in-progress "play all"
      // sequence (playOnly() stops it) — make sure the sequence's own button
      // doesn't stay stuck disabled since its onDone will now never fire.
      playBtn.disabled = false;
      markPlaying(i);
      ctrl.playOnly(i, () => markPlaying(-1));
    });
    seq.appendChild(el);
    return el;
  });

  function markPlaying(i) {
    segEls.forEach((e, idx) => e.classList.toggle("playing", idx === i));
  }

  playBtn.addEventListener("click", () => {
    playBtn.disabled = true;
    ctrl.playAll(
      (i) => markPlaying(i),
      () => {
        markPlaying(-1);
        playBtn.disabled = false;
      }
    );
  });

  wrap.append(head, seq);
  turn.appendChild(wrap);
  $log.scrollTop = $log.scrollHeight;
}

/* -- feedback row: 👍 / 👎 / ✍️ Düzəliş, wired to POST /feedback by turn_id */
function appendFeedbackRow(turn, turnId, threadId) {
  if (!turnId) return;
  const row = document.createElement("div");
  row.className = "feedback-row";

  const mk = (kind, iconHtml, label) => {
    const b = document.createElement("button");
    b.type = "button";
    b.className = "fbtn on-" + kind;
    b.innerHTML = iconHtml;
    if (label) b.appendChild(document.createTextNode(" " + label));
    b.addEventListener("click", async () => {
      let text;
      if (kind === "corr") {
        text = prompt("Bu cavab əvəzinə nə deyilməli idi?");
        if (text === null) return;
        text = text.trim();
        if (!text) return;
      }
      b.disabled = true;
      try {
        await api.feedback({
          turn_id: turnId,
          thread_id: threadId,
          kind: kind === "corr" ? "correction" : kind,
          text: kind === "corr" ? text : undefined,
        });
        b.classList.add("sent");
        toast(
          kind === "up"
            ? "👍 Təşəkkürlər — qeydə alındı."
            : kind === "down"
            ? "👎 Qeydə alındı, təşəkkürlər."
            : "✍️ Düzəliş qeydə alındı, təşəkkürlər.",
          "ok"
        );
        refreshStats();
      } catch (err) {
        b.disabled = false;
        toast("Rəy göndərilmədi: " + err.message, "err");
      }
    });
    return b;
  };

  row.append(mk("up", ICONS.up), mk("down", ICONS.down), mk("corr", ICONS.pencil, "Düzəliş"));
  turn.appendChild(row);
  $log.scrollTop = $log.scrollHeight;
}

/* -- pending-approval box: Təsdiqlə / Redaktə et / İmtina, resolved through
   /chat/resume or /voice/resume depending which channel raised it. */
function appendPendingBox(turn, approval, modality) {
  const bubble = document.createElement("div");
  bubble.className = "msg pending";
  const via = document.createElement("div");
  via.className = "via";
  via.innerHTML = ICONS.clock;
  via.appendChild(document.createTextNode(" GÖZLƏYİR — " + (approval.advisor || "Divan")));
  bubble.appendChild(via);
  const q = document.createElement("div");
  q.textContent = approval.question || "";
  bubble.appendChild(q);
  if (approval.draft) {
    const d = document.createElement("div");
    d.style.marginTop = "6px";
    d.style.color = "var(--ink2)";
    d.style.fontStyle = "italic";
    d.textContent = "“" + approval.draft + "”";
    bubble.appendChild(d);
  }
  turn.appendChild(bubble);

  const box = document.createElement("div");
  box.className = "approval-box";
  const approveBtn = document.createElement("button");
  approveBtn.type = "button";
  approveBtn.className = "btn approve";
  approveBtn.textContent = "✅ Təsdiqlə";
  const editBtn = document.createElement("button");
  editBtn.type = "button";
  editBtn.className = "btn edit";
  editBtn.textContent = "✏️ Redaktə et";
  const rejectBtn = document.createElement("button");
  rejectBtn.type = "button";
  rejectBtn.className = "btn reject";
  rejectBtn.textContent = "🚫 İmtina";
  box.append(approveBtn, editBtn, rejectBtn);
  turn.appendChild(box);
  $log.scrollTop = $log.scrollHeight;

  const disableAll = () => [approveBtn, editBtn, rejectBtn].forEach((b) => (b.disabled = true));
  const enableAll = () => [approveBtn, editBtn, rejectBtn].forEach((b) => (b.disabled = false));

  async function finish(decision, text) {
    disableAll();
    try {
      const data =
        modality === "text" ? await api.chatResume(decision, text) : await api.voiceResume(decision, text);
      state.pending = null;
      setSteps({ hitl: "done", memory: "done" });
      bubble.remove();
      box.remove();
      const cls = decision === "reject" ? "rejected" : "bot";
      appendBotBubble(turn, data.reply, cls);
      const consulted =
        modality === "voice" ? (data.segments || []).filter((s) => s.advisor).map((s) => s.advisor) : data.consulted || [];
      if (consulted.length) appendChips(turn, consulted);
      if (modality === "voice") appendPlayer(turn, data.segments);
      appendFeedbackRow(turn, data.turn_id, data.thread_id);
      toast(
        "Qərar qeydə alındı: " + (decision === "approve" ? "təsdiqləndi" : decision === "edit" ? "redaktə edildi" : "imtina edildi"),
        "ok"
      );
    } catch (err) {
      toast("Xəta: " + err.message, "err");
      enableAll();
    }
  }

  approveBtn.addEventListener("click", () => finish("approve"));
  rejectBtn.addEventListener("click", () => finish("reject"));
  editBtn.addEventListener("click", () => {
    const text = prompt("Əvəz mətni:", approval.draft || "");
    if (text === null) return;
    const trimmed = text.trim();
    if (!trimmed) return;
    finish("edit", trimmed);
  });
}

/* Citations — the receipt behind a grounded reply: which real passages the
   consulted advisors leaned on ({work, ref, quote}). */
function appendCitations(turn, citations) {
  if (!citations || !citations.length) return;
  const box = document.createElement("div");
  box.className = "citations";
  const head = document.createElement("div");
  head.className = "citations-head";
  head.textContent = "📜 Mənbələr";
  box.appendChild(head);
  citations.forEach((c) => {
    const row = document.createElement("div");
    row.className = "citation";
    const quote = document.createElement("span");
    quote.className = "citation-quote";
    quote.textContent = "«" + c.quote + (c.quote.length >= 160 ? "…" : "") + "»";
    const ref = document.createElement("span");
    ref.className = "citation-ref";
    ref.textContent = "— " + (c.name ? c.name + ": " : "") + c.work + ", " + c.ref;
    row.append(quote, ref);
    box.appendChild(row);
  });
  turn.appendChild(box);
}

/* ---------------------------------------------------------------------- *
 * Text chat flow
 * ---------------------------------------------------------------------- */

async function submitText(message) {
  if (state.pending) {
    toast("Əvvəlcə gözləyən qərarı həll edin.", "err");
    return;
  }
  resetSteps();
  resetChamber();
  chamberThinking(true);
  setSteps({ route: "live" });

  const turn = startTurn(message, { via: "text" });

  try {
    const data = await api.chat(message);
    setSteps({ route: "done", advisors: "done", synthesize: "done" });
    revealConsulted(data.consulted || []);

    if (data.status === "pending_approval") {
      setSteps({ hitl: "live" });
      state.pending = { modality: "text" };
      appendPendingBox(turn, data.approval || {}, "text");
    } else {
      setSteps({ hitl: "done", memory: "done" });
      appendBotBubble(turn, data.reply, "bot");
      appendChips(turn, data.consulted);
      appendCitations(turn, data.citations);
      appendFeedbackRow(turn, data.turn_id, data.thread_id);
    }
  } catch (err) {
    chamberThinking(false);
    appendBotBubble(turn, "Xəta baş verdi: " + err.message, "rejected");
    toast("Sorğu uğursuz oldu: " + err.message, "err");
  }
}

$form.addEventListener("submit", (e) => {
  e.preventDefault();
  const val = $input.value.trim();
  if (!val) return;
  $input.value = "";
  submitText(val);
});

/* ---------------------------------------------------------------------- *
 * Voice flow — MediaRecorder -> POST /voice -> sequential segment playback
 * ---------------------------------------------------------------------- */

let mediaRecorder = null;
let mediaStream = null;
let mediaChunks = [];
let recTimerHandle = null;
let recSeconds = 0;

function pickMimeType() {
  const candidates = ["audio/webm;codecs=opus", "audio/webm", "audio/ogg;codecs=opus", "audio/mp4"];
  if (!window.MediaRecorder || !MediaRecorder.isTypeSupported) return "";
  for (const c of candidates) {
    if (MediaRecorder.isTypeSupported(c)) return c;
  }
  return "";
}
function extFor(mime) {
  if (!mime) return "webm";
  if (mime.includes("webm")) return "webm";
  if (mime.includes("ogg")) return "ogg";
  if (mime.includes("mp4")) return "m4a";
  if (mime.includes("wav")) return "wav";
  return "webm";
}
function fmtTimer(s) {
  const m = Math.floor(s / 60);
  const r = s % 60;
  return String(m).padStart(2, "0") + ":" + String(r).padStart(2, "0");
}

async function startRecording() {
  if (state.pending) {
    toast("Əvvəlcə gözləyən qərarı həll edin.", "err");
    return;
  }
  $voiceError.textContent = "";
  if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
    $voiceError.textContent =
      "Brauzer bu ünvanda mikrofonu açmır — mikrofon yalnız HTTPS və ya localhost-da işləyir. " +
      "Səs Məktəbi tabındakı «Fayl yüklə» ilə hazır yazı göndərə bilərsiniz.";
    reportClientError("mic-unavailable", "insecure origin, getUserMedia missing");
    return;
  }
  try {
    mediaStream = await navigator.mediaDevices.getUserMedia({ audio: true });
  } catch (err) {
    $voiceError.textContent = "Mikrofona icazə verilmədi (" + err.message + ").";
    return;
  }
  const mime = pickMimeType();
  try {
    mediaRecorder = mime ? new MediaRecorder(mediaStream, { mimeType: mime }) : new MediaRecorder(mediaStream);
  } catch {
    mediaRecorder = new MediaRecorder(mediaStream);
  }
  mediaChunks = [];
  mediaRecorder.ondataavailable = (e) => {
    if (e.data && e.data.size > 0) mediaChunks.push(e.data);
  };
  mediaRecorder.onstop = onRecordingStop;
  mediaRecorder.start();

  recSeconds = 0;
  $recTimer.textContent = fmtTimer(0);
  recTimerHandle = setInterval(() => {
    recSeconds++;
    $recTimer.textContent = fmtTimer(recSeconds);
  }, 1000);

  $micBtn.classList.add("recording");
  $micLabel.textContent = "Dayandır";
}

function stopRecording() {
  if (mediaRecorder && mediaRecorder.state !== "inactive") mediaRecorder.stop();
  if (mediaStream) mediaStream.getTracks().forEach((t) => t.stop());
  clearInterval(recTimerHandle);
  $micBtn.classList.remove("recording");
  $micLabel.textContent = "Danış";
}

async function onRecordingStop() {
  const mime = (mediaRecorder && mediaRecorder.mimeType) || "audio/webm";
  const blob = new Blob(mediaChunks, { type: mime });
  if (blob.size < 400) {
    $voiceError.textContent = "Səs yazısı çox qısa oldu — bir az daha uzun danışın.";
    return;
  }
  await submitVoice(blob, mime);
}

$micBtn.addEventListener("click", () => {
  if (mediaRecorder && mediaRecorder.state === "recording") stopRecording();
  else startRecording();
});

async function submitVoice(blob, mime) {
  if (state.pending) {
    toast("Əvvəlcə gözləyən qərarı həll edin.", "err");
    return;
  }
  resetSteps();
  resetChamber();
  chamberThinking(true);
  setSteps({ route: "live" });

  const turn = startTurn("🎙 Səs yazısı göndərilir…", { via: "voice" });

  try {
    const fd = new FormData();
    fd.append("file", blob, "recording." + extFor(mime));
    fd.append("thread_id", state.threadId);
    const data = await api.voice(fd);

    updateTurnUserText(turn, data.transcript && data.transcript.trim() ? data.transcript : "(danışıq mətni boş gəldi)");

    const consulted = (data.segments || []).filter((s) => s.advisor).map((s) => s.advisor);
    setSteps({ route: "done", advisors: "done", synthesize: "done" });
    revealConsulted(consulted);

    // VoiceResponse has no explicit `status`/`approval` field (unlike
    // ChatResponse) — but TurnResult always sets history_length=0 for a
    // pending_approval turn and only for that case (see app/graph/builder.py
    // _extract_result / get_pending), so it is a reliable, code-grounded
    // signal here, not a guess.
    const isPending = data.history_length === 0;

    if (isPending) {
      setSteps({ hitl: "live" });
      const draftSeg = (data.segments || [])[0];
      const approval = {
        advisor: draftSeg ? draftSeg.name : "Divan",
        advisor_key: draftSeg ? draftSeg.advisor : "",
        question: data.reply,
        draft: draftSeg ? draftSeg.text : "",
      };
      state.pending = { modality: "voice" };
      appendPendingBox(turn, approval, "voice");
      appendPlayer(turn, data.segments);
    } else {
      setSteps({ hitl: "done", memory: "done" });
      appendBotBubble(turn, data.reply, "bot");
      appendChips(turn, consulted);
      appendPlayer(turn, data.segments);
      appendFeedbackRow(turn, data.turn_id, data.thread_id);
    }
  } catch (err) {
    chamberThinking(false);
    updateTurnUserText(turn, "🎙 (səs tanınmadı)");
    toast("Səs sorğusu uğursuz oldu: " + err.message, "err");
  }
}

/* ---------------------------------------------------------------------- *
 * Mode tabs (Yazı / Səs)
 * ---------------------------------------------------------------------- */

document.querySelectorAll(".modes button").forEach((btn) => {
  btn.addEventListener("click", () => {
    document.querySelectorAll(".modes button").forEach((b) => b.classList.remove("on"));
    btn.classList.add("on");
    const mode = btn.dataset.mode;
    document.querySelectorAll(".mode-panel").forEach((p) => p.classList.toggle("on", p.dataset.mode === mode));
  });
});

/* ---------------------------------------------------------------------- *
 * Feedback stats mini-widget — GET /feedback/stats
 * ---------------------------------------------------------------------- */

function compactNumber(n) {
  n = Number(n) || 0;
  if (n >= 1000000) return (n / 1000000).toFixed(1).replace(/\.0$/, "") + "M";
  if (n >= 1000) return (n / 1000).toFixed(1).replace(/\.0$/, "") + "K";
  return String(n);
}

function statTile(cls, icon, n, label) {
  return (
    '<div class="fbstat ' +
    cls +
    '">' +
    icon +
    '<div class="nl"><span class="n">' +
    compactNumber(n) +
    '</span><span class="l">' +
    label +
    "</span></div></div>"
  );
}

async function refreshStats() {
  try {
    const s = await api.feedbackStats();
    $fbstats.innerHTML =
      statTile("up", ICONS.up, s.up, "Bəyəndi") +
      statTile("down", ICONS.down, s.down, "Bəyənmədi") +
      statTile("corr", ICONS.pencil, s.correction, "Düzəliş") +
      statTile("total", ICONS.hash, s.total, "Cəmi");
  } catch {
    $fbstats.innerHTML = '<div class="fbstats-loading">Statistika yüklənmədi</div>';
  }
}

/* ---------------------------------------------------------------------- *
 * Voice Lab (Səs Məktəbi) — teach the narrator clone, sentence by sentence.
 * Mirrors the Telegram /ses flow: read the target sentence aloud, get a
 * word-level trainer-vs-clone comparison back, recording becomes cloning
 * material. File upload is the fallback for insecure origins (plain HTTP),
 * where the browser refuses getUserMedia.
 * ---------------------------------------------------------------------- */

const $labSentence = document.getElementById("lab-sentence");
const $labFocus = document.getElementById("lab-focus");
const $labRemaining = document.getElementById("lab-remaining");
const $labMic = document.getElementById("lab-mic");
const $labMicLabel = document.getElementById("lab-mic-label");
const $labTimer = document.getElementById("lab-timer");
const $labFile = document.getElementById("lab-file");
const $labSkip = document.getElementById("lab-skip");
const $labError = document.getElementById("lab-error");
const $labResults = document.getElementById("lab-results");

let lab = null;
let labRecorder = null;
let labStream = null;
let labChunks = [];
let labTimerHandle = null;
let labSeconds = 0;

async function labLoad(skip) {
  try {
    lab = await api.voicelabNext(skip);
    $labSentence.textContent = "«" + lab.text + "»";
    $labFocus.textContent = "🎯 " + lab.focus;
    $labRemaining.textContent = lab.remaining + " cümlə qalıb";
  } catch (err) {
    $labSentence.textContent = "Cümləni yükləyə bilmədim.";
    $labError.textContent = err.message;
  }
}

async function labStartRecording() {
  $labError.textContent = "";
  if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
    $labError.textContent =
      "Bu ünvanda brauzer mikrofonu açmır (HTTPS tələb edir) — sağdakı «Fayl yüklə» ilə hazır yazını göndər.";
    return;
  }
  try {
    labStream = await navigator.mediaDevices.getUserMedia({ audio: true });
  } catch (err) {
    $labError.textContent = "Mikrofona icazə verilmədi (" + err.message + ").";
    return;
  }
  const mime = pickMimeType();
  try {
    labRecorder = mime ? new MediaRecorder(labStream, { mimeType: mime }) : new MediaRecorder(labStream);
  } catch {
    labRecorder = new MediaRecorder(labStream);
  }
  labChunks = [];
  labRecorder.ondataavailable = (e) => {
    if (e.data && e.data.size > 0) labChunks.push(e.data);
  };
  labRecorder.onstop = () => {
    const mimeType = (labRecorder && labRecorder.mimeType) || "audio/webm";
    const blob = new Blob(labChunks, { type: mimeType });
    if (blob.size < 400) {
      $labError.textContent = "Yazı çox qısa oldu — cümləni tam oxu.";
      return;
    }
    labSubmit(blob, "reading." + extFor(mimeType));
  };
  labRecorder.start();

  labSeconds = 0;
  $labTimer.textContent = fmtTimer(0);
  labTimerHandle = setInterval(() => {
    labSeconds++;
    $labTimer.textContent = fmtTimer(labSeconds);
  }, 1000);

  $labMic.classList.add("recording");
  $labMicLabel.textContent = "Dayandır";
}

function labStopRecording() {
  if (labRecorder && labRecorder.state !== "inactive") labRecorder.stop();
  if (labStream) labStream.getTracks().forEach((t) => t.stop());
  clearInterval(labTimerHandle);
  $labMic.classList.remove("recording");
  $labMicLabel.textContent = "Oxu";
}

function labDiffLine(label, transcript, diffs) {
  const wrap = document.createElement("div");
  wrap.className = "lab-cmp";
  const head = document.createElement("b");
  head.textContent = label;
  const said = document.createElement("div");
  said.className = "lab-said";
  said.textContent = transcript || "(boş)";
  const diff = document.createElement("div");
  diff.className = "lab-diffs" + (diffs.length ? " bad" : " good");
  diff.textContent = diffs.length
    ? diffs.map((d) => "«" + d.expected + "» → «" + (d.heard || "(düşüb)") + "»").join(";  ")
    : "fərq yoxdur ✅";
  wrap.append(head, said, diff);
  return wrap;
}

async function labSubmit(blob, filename) {
  if (!lab) return;
  $labError.textContent = "";
  const box = document.createElement("div");
  box.className = "lab-result";
  box.textContent = "⏳ Təhlil olunur — Whisper hər iki oxunuşu dinləyir…";
  $labResults.prepend(box);
  try {
    const fd = new FormData();
    fd.append("file", blob, filename);
    fd.append("expected_text", lab.text);
    fd.append("index", String(lab.index));
    const data = await api.voicelabSample(fd);

    box.textContent = "";
    const title = document.createElement("div");
    title.className = "lab-result-title";
    title.textContent = "«" + lab.text + "»";
    box.appendChild(title);
    box.appendChild(labDiffLine("👤 Səndən eşidilən", data.trainer_transcript, data.trainer_diffs));
    box.appendChild(labDiffLine("🤖 Klondan eşidilən", data.clone_transcript, data.clone_diffs));
    const audio = document.createElement("audio");
    audio.controls = true;
    audio.src = b64ToBlobUrl(data.clone_audio_base64, data.clone_audio_mime || "audio/ogg");
    box.appendChild(audio);

    toast("Yazı qəbul olundu — klon materialına əlavə edildi.");
    labLoad();
  } catch (err) {
    box.remove();
    $labError.textContent = "Göndərmə alınmadı: " + err.message;
  }
}

$labMic.addEventListener("click", () => {
  if (labRecorder && labRecorder.state === "recording") labStopRecording();
  else labStartRecording();
});

$labFile.addEventListener("change", () => {
  const file = $labFile.files && $labFile.files[0];
  if (file) labSubmit(file, file.name);
  $labFile.value = "";
});

$labSkip.addEventListener("click", () => labLoad(lab ? lab.index : undefined));

/* ---------------------------------------------------------------------- *
 * Init
 * ---------------------------------------------------------------------- */

refreshStats();
setInterval(refreshStats, 30000);
labLoad();
