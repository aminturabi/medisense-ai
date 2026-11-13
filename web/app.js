const $ = s => document.querySelector(s);
let current = null, lang = "en", ocrBusy = false;

const SAMPLES = {
  rx: "Dr. Ahmed Khan, City Clinic\nPatient: Test, CNIC 35202-1234567-1, 0300-1234567\n\nTab. Augmentin 625 mg BD x 5 days\nTab. Panadol 500 mg TDS x 3 days\nCap. Risek 20 mg OD x 14 days",
  lab: "City Lab - Blood Report\nHemoglobin 11.2 g/dL\nWBC 8500 /uL\nPlatelets 230000 /uL\nGlucose 182 mg/dL\nPotassium 4.3 mmol/L\nCreatinine 0.9 mg/dL",
  emergency: "City Lab - Emergency Panel\nHemoglobin 6.4 g/dL\nPotassium 6.9 mmol/L\nGlucose 92 mg/dL\nSodium 138 mmol/L\n\nTab. Disprin 75 mg OD\nTab. Warfarin 5 mg OD"
};
$("#sampleRx").onclick = () => { $("#inputText").value = SAMPLES.rx; run(); };
$("#sampleLab").onclick = () => { $("#inputText").value = SAMPLES.lab; run(); };
$("#sampleEmergency").onclick = () => { $("#inputText").value = SAMPLES.emergency; run(); };
$("#analyzeBtn").onclick = run;

// --- Photo: blur check (Laplacian variance on a small canvas) + Tesseract.js OCR (printed text) ---
$("#photo").onchange = async e => {
  const file = e.target.files[0]; if (!file) return;
  ocrBusy = true;
  $("#analyzeBtn").textContent = "⏳ Reading your photo… please wait";
  const img = $("#preview"); img.src = URL.createObjectURL(file); img.hidden = false;
  await new Promise(r => img.onload = r);
  const c = document.createElement("canvas");
  const scale = Math.min(1, 400 / img.naturalWidth);
  c.width = img.naturalWidth * scale; c.height = img.naturalHeight * scale;
  const ctx = c.getContext("2d"); ctx.drawImage(img, 0, 0, c.width, c.height);
  const d = ctx.getImageData(0, 0, c.width, c.height).data;
  const gray = [];
  for (let i = 0; i < d.length; i += 4) gray.push(0.299 * d[i] + 0.587 * d[i + 1] + 0.114 * d[i + 2]);
  const w = c.width, lap = [];
  for (let y = 1; y < c.height - 1; y++) for (let x = 1; x < w - 1; x++) {
    const i = y * w + x;
    lap.push(gray[i - w] + gray[i + w] + gray[i - 1] + gray[i + 1] - 4 * gray[i]);
  }
  const mean = lap.reduce((a, b) => a + b, 0) / lap.length;
  const variance = lap.reduce((a, b) => a + (b - mean) ** 2, 0) / lap.length;
  if (variance < 100) {
    $("#photoStatus").textContent = "⚠ This photo looks blurry (sharpness " + Math.round(variance) + "). Please take it again in good light, close and straight - blurry photos are not read, for your safety.";
    ocrBusy = false; $("#analyzeBtn").textContent = "Explain it simply →";
    return;
  }
  $("#photoStatus").textContent = "Photo is sharp enough (sharpness " + Math.round(variance) + "). Reading the printed text… this can take 20-90 seconds on a phone. Please wait - it will explain automatically, do not tap Explain yet.";
  try {
    const rawText = await ocrImage(file);
    // Privacy BEFORE display: mask phone / CNIC numbers in the OCR text
    // itself, so the review box never shows the real numbers.
    const safeText = redact(rawText);
    $("#inputText").value = safeText;
    $("#photoStatus").textContent = "Text read from the photo." +
      (safeText !== rawText ? " Phone / CNIC numbers have been hidden for privacy." : "") +
      " Please check it below, fix any wrong word or number, then it is already explained:";
    ocrBusy = false; $("#analyzeBtn").textContent = "Explain it simply →";
    run();
  } catch (err) {
    ocrBusy = false; $("#analyzeBtn").textContent = "Explain it simply →";
    $("#photoStatus").textContent = "Photo reading failed (needs internet the first time). Please type or paste the report text instead.";
  }
};

// OCR works far better on a big, clean black-on-white image than on a raw
// phone photo: upscale small images, convert to grey, then binarize (Otsu).
async function ocrImage(file) {
  const bmp = await createImageBitmap(file);
  const scale = bmp.width < 1600 ? Math.min(3, 2000 / bmp.width) : 1;
  const cv = document.createElement("canvas");
  cv.width = Math.round(bmp.width * scale); cv.height = Math.round(bmp.height * scale);
  const cx = cv.getContext("2d");
  cx.fillStyle = "#fff"; cx.fillRect(0, 0, cv.width, cv.height);
  cx.drawImage(bmp, 0, 0, cv.width, cv.height);
  const id = cx.getImageData(0, 0, cv.width, cv.height), px = id.data;
  const hist = new Array(256).fill(0), grey = new Uint8Array(px.length / 4);
  for (let i = 0, j = 0; i < px.length; i += 4, j++) {
    grey[j] = Math.round(0.299 * px[i] + 0.587 * px[i + 1] + 0.114 * px[i + 2]);
    hist[grey[j]]++;
  }
  let sum = 0; for (let t = 0; t < 256; t++) sum += t * hist[t];
  let sumB = 0, wB = 0, best = 0, thr = 127;
  for (let t = 0; t < 256; t++) {
    wB += hist[t]; if (!wB) continue;
    const wF = grey.length - wB; if (!wF) break;
    sumB += t * hist[t];
    const between = wB * wF * ((sumB / wB) - ((sum - sumB) / wF)) ** 2;
    if (between > best) { best = between; thr = t; }
  }
  for (let i = 0, j = 0; i < px.length; i += 4, j++) {
    const v = grey[j] > thr ? 255 : 0;
    px[i] = px[i + 1] = px[i + 2] = v;
  }
  cx.putImageData(id, 0, 0);
  if (Tesseract.createWorker) {
    const worker = await Tesseract.createWorker("eng", 1, {
      logger: m => {
        if (m.status === "recognizing text" && ocrBusy)
          $("#photoStatus").textContent = "⏳ Reading your photo… " + Math.round((m.progress || 0) * 100) + "% - please wait, it will explain automatically.";
      }
    });
    try {
      await worker.setParameters({ tessedit_pageseg_mode: "6", preserve_interword_spaces: "1" });
      const { data } = await worker.recognize(cv);
      return cleanOcrData(data);
    } finally { await worker.terminate(); }
  }
  return cleanOcrData((await Tesseract.recognize(cv, "eng")).data);
}

// Drop OCR noise BEFORE the text is shown: low-confidence words, pure-symbol
// tokens (logo / QR junk like © | ~) and stray single characters are removed
// line by line. Single letters/digits with decent confidence are kept -
// an "x" in "BD x 5 days" and a lone dose number are real content.
function cleanOcrData(data) {
  const keepWord = (text, conf) => {
    if (conf != null && conf < 45) return false;          // low-confidence noise
    if (!/[A-Za-z0-9]/.test(text)) return false;           // pure symbols / junk
    if (text.length === 1 && !/[A-Za-z0-9]/.test(text)) return false;
    return true;
  };
  if (data && Array.isArray(data.lines) && data.lines.length && data.lines[0].words) {
    return data.lines
      .map(line => (line.words || []).filter(w => keepWord(w.text, w.confidence)).map(w => w.text).join(" "))
      .filter(t => t.trim().length > 1)
      .join("\n");
  }
  // Fallback when word data is unavailable: same token rules, no confidence.
  return (data && data.text ? data.text : "")
    .split("\n")
    .map(line => line.split(/\s+/).filter(t => t && keepWord(t, null)).join(" "))
    .filter(t => t.trim().length > 1)
    .join("\n");
}

async function run() {
  const text = $("#inputText").value.trim();
  if (!text) {
    if (ocrBusy || !$("#preview").hidden) {
      // A photo IS added - it is still being read. Never claim otherwise.
      $("#photoStatus").textContent = "⏳ Your photo is added and still being read. Please wait a few more seconds - the explanation will appear automatically, no need to tap Explain.";
      $("#photoStatus").scrollIntoView({ behavior: "smooth", block: "center" });
    } else {
      alert("Please add a photo, a sample, or paste the report text first.");
    }
    return;
  }
  // Prefer the Python API when the page is served by server.py; fall back to the JS engine for static hosting.
  try {
    const r = await fetch("/api/analyze", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ text }) });
    if (!r.ok) throw new Error("api");
    current = await r.json();
  } catch { current = analyzeLocal(text); }
  render();
}

const DOSE_ICON = { OD: "🌅", BD: "🌅 🌙", BID: "🌅 🌙", TDS: "🌅 ☀️ 🌙", TID: "🌅 ☀️ 🌙", QID: "🌅 ☀️ 🌇 🌙", HS: "🌙", SOS: "❗", PRN: "❗" };
const STATUS_LABEL = { normal: "Normal ✅", high: "High ⬆", low: "Low ⬇", critical_high: "DANGER - VERY HIGH 🚨", critical_low: "DANGER - VERY LOW 🚨", suspect_decimal: "CHECK NUMBER ⚠" };

function render() {
  $("#results").hidden = false;
  const b = $("#emergencyBanner");
  b.hidden = !current.emergency;
  if (current.emergency) b.querySelector("span").textContent =
    "One of your results is in the DANGER range. Go to the nearest hospital emergency now, or call Rescue 1122.";
  $("#alertsBox").innerHTML = current.alerts.filter(a => a.severity !== "emergency")
    .map(a => `<div class="alert ${a.severity}">⚠ <b>${a.drug}:</b> ${a.message_en}</div>`).join("");
  $("#medCard").hidden = !current.medications.length;
  $("#medList").innerHTML = current.medications.map(m => `
    <div class="med"><h3>${m.generic} <span class="chip">${m.name_as_written}</span> <span class="chip">${m.strength} ${m.unit}</span>
    ${m.days ? `<span class="chip">${m.days} days</span>` : ""}</h3>
    <div class="doses">${DOSE_ICON[m.frequency] || ""}</div>
    <div>${m.purpose_en}</div><div>⚠ ${m.precaution_en}</div></div>`).join("");
  $("#labCard").hidden = !current.lab_results.length;
  $("#labList").innerHTML = current.lab_results.map(l => `
    <div class="lab"><div><b>${l.name}</b><br><small>Normal: ${l.normal_text}</small></div>
    <div><b>${l.value} ${l.unit}</b></div><span class="pill ${l.status}">${STATUS_LABEL[l.status]}</span></div>`).join("");
  $("#unverifiedCard").hidden = !current.unverified_items.length;
  $("#unverifiedList").innerHTML = current.unverified_items
    .map(u => `<div class="unv"><b>${u.raw_name} ${u.strength} ${u.unit}</b> - could not be verified automatically.</div>`).join("");
  showLang();
  $("#results").scrollIntoView({ behavior: "smooth" });
}

function isDisclaimer(line) {
  return line.includes("does not replace your doctor") || line.includes("متبادل نہیں ہے") || line.includes("ځای نه نیسي");
}
function showLang() {
  if (!current) return;
  const box = $("#explanation");
  // Exactly ONE disclaimer, at the bottom, in the selected language only -
  // strip any disclaimer lines the engine added (any language), then add ours.
  const lines = current.explanations[lang].filter(l => !isDisclaimer(l));
  lines.push(DISCLAIMER[lang]);
  box.textContent = lines.join("\n");
  box.dir = lang === "en" ? "ltr" : "rtl";
}
document.querySelectorAll(".lang").forEach(btn => btn.onclick = () => {
  lang = btn.dataset.lang;
  document.querySelectorAll(".lang").forEach(x => x.classList.toggle("active", x === btn));
  showLang();
});

$("#speakBtn").onclick = () => {
  if (!current) return;
  speechSynthesis.cancel();
  const u = new SpeechSynthesisUtterance(current.explanations[lang].join(". "));
  u.lang = lang === "ur" ? "ur-PK" : lang === "ps" ? "ps-AF" : "en-US";
  u.rate = 0.92;
  speechSynthesis.speak(u);
};
$("#stopBtn").onclick = () => speechSynthesis.cancel();
