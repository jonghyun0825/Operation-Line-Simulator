/* 가상 조립라인 프론트엔드.
 * 택트 동기화 규칙(F2): 단 하나의 상태 머신(LineEngine)이 라인 전체 상태를 소유하고,
 * 두 헤드(M1, M2)는 매 프레임 이 상태를 "읽어서 렌더링만" 한다 — 별도 타이머를 갖지 않는다.
 * 조건 배율 계산(택트 시간)은 서버(config.tact_times)에서만 이뤄지며, 프론트는 그 값을 그대로 사용한다.
 */

const SVG_NS = "http://www.w3.org/2000/svg";

// ── 라인 좌표 (SVG viewBox 0 0 900 300 기준) ──
const SLOT_X = [170, 320, 470, 620]; // IN, ST1, MID, ST2
// 투입구 시작 x는 IN 슬롯과 동일한 표준 피치(150px)만큼 떨어뜨려, 등장 이동이 다른 슬롯 간
// 이송과 동일한 속도로 진행되게 한다(겹침 방지 — feederClip과 함께 동작).
const FEEDER_X = SLOT_X[0] - 150; // = 20
const CART_X = 780;
const HEAD_UP_Y = 90;
const HEAD_DOWN_Y = 180;

// 반제품 위 막대 폭과 나사 지점(20%/80%) — 나사 표시와 헤드 가로 위치가 이 상수 하나만
// 공유하도록 해서 "비트 접촉 지점 = 나사 위치"가 구조적으로 어긋날 수 없게 한다.
const UNIT_TOP_BAR_WIDTH = 94;
const SCREW_INSET_RATIO = 0.2; // 막대 폭의 20% 지점(왼쪽) / 80% 지점(오른쪽)
const SCREW_OFFSET_X = UNIT_TOP_BAR_WIDTH * (0.5 - SCREW_INSET_RATIO); // 슬롯 중심 기준 좌우 오프셋
const HEAD_M1_X = SLOT_X[1] - SCREW_OFFSET_X; // ST1 헤드: 왼쪽 나사 지점 위
const HEAD_M2_X = SLOT_X[3] + SCREW_OFFSET_X; // ST2 헤드: 오른쪽 나사 지점 위

const unitsLayer = document.getElementById("unitsLayer");
const headM1 = document.getElementById("headM1");
const headM2 = document.getElementById("headM2");
const counterText = document.getElementById("counterText");

function ease(t) {
  return t * t * (3 - 2 * t); // smoothstep
}

function setHeadPosition(el, x, y) {
  el.setAttribute("transform", `translate(${x},${y})`);
}

function createScrew(cx, cy) {
  const g = document.createElementNS(SVG_NS, "g");
  g.setAttribute("transform", `translate(${cx},${cy})`);
  g.classList.add("screw-mark");
  g.style.display = "none";

  const circle = document.createElementNS(SVG_NS, "circle");
  circle.setAttribute("r", 4);
  circle.setAttribute("fill", "#4b5563");

  const l1 = document.createElementNS(SVG_NS, "line");
  l1.setAttribute("x1", -2.5); l1.setAttribute("y1", 0);
  l1.setAttribute("x2", 2.5); l1.setAttribute("y2", 0);
  l1.setAttribute("stroke", "#1f2937"); l1.setAttribute("stroke-width", "1");

  const l2 = document.createElementNS(SVG_NS, "line");
  l2.setAttribute("x1", 0); l2.setAttribute("y1", -2.5);
  l2.setAttribute("x2", 0); l2.setAttribute("y2", 2.5);
  l2.setAttribute("stroke", "#1f2937"); l2.setAttribute("stroke-width", "1");

  g.appendChild(circle);
  g.appendChild(l1);
  g.appendChild(l2);
  return g;
}

function createUnitGroup(unit) {
  const g = document.createElementNS(SVG_NS, "g");
  g.classList.add("unit");
  g.dataset.sn = unit.sn;
  // 투입구 개구부 뒤에서 서서히 드러나며 등장하도록 클립 적용.
  // 클립 경계(x=100)는 라인 위 모든 정지 위치보다 왼쪽이라 등장 이후에는 아무 영향이 없다.
  g.setAttribute("clip-path", "url(#feederClip)");

  const bottom = document.createElementNS(SVG_NS, "rect");
  bottom.setAttribute("x", -55); bottom.setAttribute("y", 194);
  bottom.setAttribute("width", 110); bottom.setAttribute("height", 16);
  bottom.setAttribute("rx", 3);
  bottom.setAttribute("fill", "url(#doorGradient)");
  bottom.setAttribute("stroke", "#94a3b8"); bottom.setAttribute("stroke-width", "0.5");

  const top = document.createElementNS(SVG_NS, "rect");
  top.setAttribute("x", -47); top.setAttribute("y", 179);
  top.setAttribute("width", 94); top.setAttribute("height", 15);
  top.setAttribute("rx", 3);
  top.setAttribute("fill", "url(#doorGradient)");
  top.setAttribute("stroke", "#94a3b8"); top.setAttribute("stroke-width", "0.5");

  g.appendChild(bottom);
  g.appendChild(top);

  const screwLeft = createScrew(-SCREW_OFFSET_X, 187);
  const screwRight = createScrew(SCREW_OFFSET_X, 187);
  g.appendChild(screwLeft);
  g.appendChild(screwRight);

  unit.el = g;
  unit.screwLeftEl = screwLeft;
  unit.screwRightEl = screwRight;
  return g;
}

/* ── 라인 상태 머신 ── */
class LineEngine {
  constructor({ lotId, quantity, tact, onProgress, onFinish }) {
    this.lotId = lotId;
    this.quantity = quantity;
    this.tact = tact; // {head_down_sec, fasten_sec, head_up_sec, index_sec} (서버 산출값)
    this.onProgress = onProgress;
    this.onFinish = onFinish;

    this.phase = "DOWN";
    this.phaseElapsed = 0;
    this.lastTs = null;
    this.measureFired = false;

    this.lineUnits = [null, null, null, null]; // IN, ST1, MID, ST2
    this.pendingSpawn = quantity;
    this.snCounter = 1;
    this.completed = 0;

    this.indexSnapshot = null;
    this.running = false;
    this._raf = null;
  }

  start() {
    this.running = true;
    this.lastTs = null;
    this._raf = requestAnimationFrame((ts) => this.tick(ts));
  }

  stop() {
    this.running = false;
    if (this._raf) cancelAnimationFrame(this._raf);
  }

  durationFor(phase) {
    switch (phase) {
      case "DOWN": return this.tact.head_down_sec;
      case "FASTEN": return this.tact.fasten_sec;
      case "UP": return this.tact.head_up_sec;
      case "INDEX": return this.tact.index_sec;
      default: return 0.001;
    }
  }

  tick(ts) {
    if (!this.running) return;
    if (this.lastTs == null) this.lastTs = ts;
    const dt = (ts - this.lastTs) / 1000;
    this.lastTs = ts;
    this.phaseElapsed += dt;

    const duration = Math.max(this.durationFor(this.phase), 0.001);
    const t = Math.min(this.phaseElapsed / duration, 1);

    this.render(t);

    if (this.phase === "DOWN" && t >= 0.999 && !this.measureFired) {
      this.measureFired = true;
      this.fireMeasurements();
    }

    if (t >= 1) {
      this.advancePhase();
    }

    if (this.running) {
      this._raf = requestAnimationFrame((ts2) => this.tick(ts2));
    }
  }

  advancePhase() {
    if (this.phase === "INDEX") {
      this.commitIndex();
      if (this.completed >= this.quantity) {
        this.running = false;
        this.onFinish();
        return;
      }
      this.phase = "DOWN";
    } else if (this.phase === "DOWN") {
      this.phase = "FASTEN";
    } else if (this.phase === "FASTEN") {
      this.phase = "UP";
    } else if (this.phase === "UP") {
      this.phase = "INDEX";
      this.prepareIndex();
    }
    this.phaseElapsed = 0;
    this.measureFired = false;
  }

  prepareIndex() {
    const old = this.lineUnits.slice();
    let spawn = null;
    if (this.pendingSpawn > 0) {
      spawn = { sn: `SN-${String(this.snCounter).padStart(4, "0")}`, screwLeft: false, screwRight: false };
      this.snCounter++;
      this.pendingSpawn--;
      const g = createUnitGroup(spawn);
      g.setAttribute("transform", `translate(${FEEDER_X},0)`);
      unitsLayer.appendChild(g);
    }
    const exiting = old[3];
    this.indexSnapshot = { old, spawn, exiting };
  }

  commitIndex() {
    const { old, spawn, exiting } = this.indexSnapshot;
    this.lineUnits = [spawn, old[0], old[1], old[2]];

    if (exiting) {
      if (exiting.el) exiting.el.remove();
      this.completed += 1;
      fetch("/api/unit-complete", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ lot_id: this.lotId, unit_sn: exiting.sn }),
      }).catch(() => {});
      this.onProgress({ completed: this.completed, quantity: this.quantity });
    }
    this.indexSnapshot = null;
  }

  fireMeasurements() {
    const st1 = this.lineUnits[1];
    const st2 = this.lineUnits[3];
    if (st1) this.measureUnit(st1, "ST1");
    if (st2) this.measureUnit(st2, "ST2");
  }

  async measureUnit(unit, station) {
    try {
      const res = await fetch("/api/measure", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ lot_id: this.lotId, unit_sn: unit.sn, station }),
      });
      if (!res.ok) return;
      await res.json();
      if (station === "ST1") {
        unit.screwLeft = true;
        if (unit.screwLeftEl) unit.screwLeftEl.style.display = "";
      } else {
        unit.screwRight = true;
        if (unit.screwRightEl) unit.screwRightEl.style.display = "";
      }
    } catch (e) {
      // 네트워크 오류가 있어도 택트 상태 머신 자체는 멈추지 않는다.
    }
  }

  render(t) {
    const et = ease(t);
    let headY;
    if (this.phase === "DOWN") headY = HEAD_UP_Y + (HEAD_DOWN_Y - HEAD_UP_Y) * et;
    else if (this.phase === "FASTEN") headY = HEAD_DOWN_Y;
    else if (this.phase === "UP") headY = HEAD_DOWN_Y + (HEAD_UP_Y - HEAD_DOWN_Y) * et;
    else headY = HEAD_UP_Y; // INDEX: 헤드는 상단에서 대기

    setHeadPosition(headM1, HEAD_M1_X, headY);
    setHeadPosition(headM2, HEAD_M2_X, headY);

    if (this.phase === "INDEX" && this.indexSnapshot) {
      const { old, spawn, exiting } = this.indexSnapshot;
      for (let i = 0; i < 3; i++) {
        const u = old[i];
        if (u && u.el) {
          const x = SLOT_X[i] + (SLOT_X[i + 1] - SLOT_X[i]) * et;
          u.el.setAttribute("transform", `translate(${x},0)`);
        }
      }
      if (spawn && spawn.el) {
        const x = FEEDER_X + (SLOT_X[0] - FEEDER_X) * et;
        spawn.el.setAttribute("transform", `translate(${x},0)`);
      }
      if (exiting && exiting.el) {
        const x = SLOT_X[3] + (CART_X - SLOT_X[3]) * et;
        exiting.el.setAttribute("transform", `translate(${x},0)`);
        exiting.el.style.opacity = String(1 - et);
      }
    } else {
      for (let i = 0; i < 4; i++) {
        const u = this.lineUnits[i];
        if (u && u.el) {
          u.el.setAttribute("transform", `translate(${SLOT_X[i]},0)`);
          u.el.style.opacity = "1";
        }
      }
    }
  }
}

/* ── 생산 조건 패널 상태 ── */
const BOX_SIZE = 10;
const TEMP_OK_RANGE = [22, 26];

const conditionState = {
  boxes: 1,
  temperature: 24,
  headSpeed: "보통",
};

const boxValueEl = document.getElementById("boxValue");
const totalQtyEl = document.getElementById("totalQty");
const tempRangeEl = document.getElementById("tempRange");
const tempValueEl = document.getElementById("tempValue");
const tempBadgeEl = document.getElementById("tempBadge");

function updateBoxDisplay() {
  boxValueEl.textContent = conditionState.boxes;
  totalQtyEl.textContent = conditionState.boxes * BOX_SIZE;
}
document.getElementById("boxDec").addEventListener("click", () => {
  if (conditionState.boxes > 1) { conditionState.boxes--; updateBoxDisplay(); }
});
document.getElementById("boxInc").addEventListener("click", () => {
  if (conditionState.boxes < 5) { conditionState.boxes++; updateBoxDisplay(); }
});

function updateTempDisplay() {
  tempValueEl.textContent = conditionState.temperature;
  const inRange = conditionState.temperature >= TEMP_OK_RANGE[0] && conditionState.temperature <= TEMP_OK_RANGE[1];
  tempBadgeEl.textContent = inRange ? "적정" : (conditionState.temperature > TEMP_OK_RANGE[1] ? "높음" : "낮음");
  tempBadgeEl.className = "temp-badge " + (inRange ? "ok" : "warn");
}
tempRangeEl.addEventListener("input", (e) => {
  conditionState.temperature = Number(e.target.value);
  updateTempDisplay();
});

function wireBtnGroup(groupId, key) {
  const group = document.getElementById(groupId);
  group.querySelectorAll("button").forEach((btn) => {
    btn.addEventListener("click", () => {
      conditionState[key] = btn.dataset.value;
      group.querySelectorAll("button").forEach((b) => b.classList.remove("selected"));
      btn.classList.add("selected");
    });
  });
}
wireBtnGroup("headSpeedGroup", "headSpeed");

updateBoxDisplay();
updateTempDisplay();

function setPanelLocked(locked) {
  document.getElementById("conditionPanel").classList.toggle("locked", locked);
  document.getElementById("lockHint").hidden = !locked;
  document.querySelectorAll("#conditionPanel input, #conditionPanel button").forEach((el) => {
    el.disabled = locked;
  });
}

/* ── F5: 현황 패널 폴링 ── */
let statusPollTimer = null;

function startStatusPolling(lotId) {
  stopStatusPolling();
  statusPollTimer = setInterval(() => pollStatus(lotId), 500);
  pollStatus(lotId);
}
function stopStatusPolling() {
  if (statusPollTimer) { clearInterval(statusPollTimer); statusPollTimer = null; }
}
async function pollStatus(lotId) {
  try {
    const res = await fetch(`/api/status/${lotId}`);
    if (!res.ok) return;
    renderStatus(await res.json());
  } catch (e) {}
}
function renderStatus(data) {
  document.getElementById("statusIdle").hidden = true;
  document.getElementById("statusContent").hidden = false;
  document.getElementById("stLotId").textContent = data.lot_id;
  document.getElementById("stTemp").textContent = data.conditions.temperature;
  document.getElementById("stHead").textContent = data.conditions.head_speed;
  document.getElementById("progressText").textContent = `${data.completed_count} / ${data.quantity}`;
  const pct = data.quantity ? (data.completed_count / data.quantity) * 100 : 0;
  document.getElementById("progressFill").style.width = pct + "%";
  document.getElementById("stOk").textContent = data.ok_count;
  document.getElementById("stNg").textContent = data.ng_count;
  document.getElementById("stDefectRate").textContent = data.defect_rate + "%";

  const ngListEl = document.getElementById("ngList");
  ngListEl.innerHTML = "";
  data.ng_events.forEach((ev) => {
    const li = document.createElement("li");
    li.textContent = `${ev.sn} · ${ev.station} · ${ev.value}`;
    ngListEl.appendChild(li);
  });
}

/* ── 메인 흐름 ── */
let engine = null;
let currentLotId = null;

document.getElementById("startBtn").addEventListener("click", async () => {
  const res = await fetch("/api/lot", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      boxes: conditionState.boxes,
      temperature: conditionState.temperature,
      head_speed: conditionState.headSpeed,
    }),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    alert("Lot 생성 실패: " + (err.detail || err.error || res.status));
    return;
  }
  const data = await res.json();
  currentLotId = data.lot_id;

  setPanelLocked(true);
  document.getElementById("postActions").hidden = true;
  counterText.textContent = `완성 0 / ${data.quantity}`;
  unitsLayer.innerHTML = "";

  engine = new LineEngine({
    lotId: data.lot_id,
    quantity: data.quantity,
    tact: data.tact_times,
    onProgress: ({ completed, quantity }) => {
      counterText.textContent = `완성 ${completed} / ${quantity}`;
    },
    onFinish: () => {
      stopStatusPolling();
      pollStatus(currentLotId);
      document.getElementById("postActions").hidden = false;
    },
  });
  engine.start();
  startStatusPolling(currentLotId);
});

document.getElementById("viewReportBtn").addEventListener("click", () => {
  if (currentLotId) window.open(`/api/report/${currentLotId}`, "_blank");
});

/* ── F7: Lot 비교 ── */
const compareModal = document.getElementById("compareModal");
const lotsTableBody = document.getElementById("lotsTableBody");
const runCompareBtn = document.getElementById("runCompareBtn");
const compareSelectionHint = document.getElementById("compareSelectionHint");
let selectedLots = []; // 최대 2개 lot_id

function updateCompareFooter() {
  compareSelectionHint.textContent = `${selectedLots.length} / 2 선택됨`;
  runCompareBtn.disabled = selectedLots.length !== 2;
}

function renderLotsTable(lots) {
  lotsTableBody.innerHTML = "";
  if (lots.length === 0) {
    lotsTableBody.innerHTML = '<tr class="empty-row"><td colspan="6">완료된 Lot이 없습니다.</td></tr>';
    return;
  }
  // 최신 Lot이 위로 오도록 정렬
  const sorted = [...lots].sort((a, b) => (a.completed_at < b.completed_at ? 1 : -1));
  sorted.forEach((lot) => {
    const tr = document.createElement("tr");
    tr.dataset.lotId = lot.lot_id;
    tr.innerHTML = `
      <td><input type="checkbox" data-lot-id="${lot.lot_id}"></td>
      <td>${lot.lot_id}</td>
      <td>${lot.temperature}°C</td>
      <td>${lot.head_speed}</td>
      <td>${lot.quantity}개</td>
      <td>${lot.defect_rate}%</td>
    `;
    tr.addEventListener("click", (e) => {
      if (e.target.tagName === "INPUT") return; // 체크박스 자체 클릭은 change 이벤트로 처리
      toggleLotSelection(lot.lot_id, tr);
    });
    const checkbox = tr.querySelector("input");
    checkbox.addEventListener("change", () => toggleLotSelection(lot.lot_id, tr, checkbox));
    lotsTableBody.appendChild(tr);
  });
}

function toggleLotSelection(lotId, tr, checkboxEl) {
  const idx = selectedLots.indexOf(lotId);
  const checkbox = checkboxEl || tr.querySelector("input");
  if (idx >= 0) {
    selectedLots.splice(idx, 1);
    tr.classList.remove("row-selected");
    checkbox.checked = false;
  } else {
    if (selectedLots.length >= 2) {
      checkbox.checked = false;
      return; // 최대 2개까지만 선택 가능
    }
    selectedLots.push(lotId);
    tr.classList.add("row-selected");
    checkbox.checked = true;
  }
  updateCompareFooter();
}

async function openCompareModal() {
  selectedLots = [];
  updateCompareFooter();
  compareModal.hidden = false;
  try {
    const res = await fetch("/api/lots");
    const lots = await res.json();
    renderLotsTable(lots);
  } catch (e) {
    lotsTableBody.innerHTML = '<tr class="empty-row"><td colspan="6">목록을 불러오지 못했습니다.</td></tr>';
  }
}

document.getElementById("openCompareBtn").addEventListener("click", openCompareModal);
document.getElementById("closeCompareBtn").addEventListener("click", () => { compareModal.hidden = true; });
compareModal.addEventListener("click", (e) => {
  if (e.target === compareModal) compareModal.hidden = true;
});

runCompareBtn.addEventListener("click", () => {
  if (selectedLots.length !== 2) return;
  const [lotA, lotB] = selectedLots;
  window.open(`/api/compare?lot_a=${encodeURIComponent(lotA)}&lot_b=${encodeURIComponent(lotB)}`, "_blank");
});

document.getElementById("newLotBtn").addEventListener("click", () => {
  setPanelLocked(false);
  document.getElementById("postActions").hidden = true;
  document.getElementById("statusContent").hidden = true;
  document.getElementById("statusIdle").hidden = false;
  unitsLayer.innerHTML = "";
  counterText.textContent = "완성 0 / 0";
  currentLotId = null;
  engine = null;
});
