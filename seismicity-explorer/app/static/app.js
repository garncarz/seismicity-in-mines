const $ = (selector) => document.querySelector(selector);
const panelSelect = $("#panel-select");
const seamSelect = $("#seam-select");
const showPanelOutlines = $("#show-panel-outlines");
const notice = $("#notice");
const map = L.map("map").setView([49.85, 18.5], 12);
L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
  maxZoom: 19,
  attribution: "&copy; OpenStreetMap contributors",
}).addTo(map);
const panelLayer = L.featureGroup().addTo(map);
const eventLayer = L.layerGroup().addTo(map);
map.createPane("coordinateGridPane");
map.getPane("coordinateGridPane").style.zIndex = 350;
const coordinateGridLayer = L.geoJSON(null, {
  pane: "coordinateGridPane",
  style: { color: "#526b78", weight: 1, dashArray: "3 6", opacity: 0.62 },
  onEachFeature: (feature, layer) => {
    const { axis, value } = feature.properties;
    layer.bindTooltip(`${axis} ${formatNumber(value, 0)} m`, {
      permanent: true,
      direction: "center",
      className: "coordinate-grid-label",
    });
  },
});
const previewLayer = L.featureGroup().addTo(map);
let panels = [];
let editingId = null;
let previewDescription = null;
let originalDescription = null;
let energyChart;
let timeChart;
let coordinateGridRequest = 0;

const formatNumber = (value, fractionDigits = 2) =>
  value === null || value === undefined ? "—" :
    Number(value).toLocaleString(undefined, { maximumFractionDigits: fractionDigits });

function showNotice(message) {
  notice.textContent = message;
  notice.classList.remove("hidden");
}

function clearNotice() {
  notice.textContent = "";
  notice.classList.add("hidden");
}

async function requestJson(url, options = {}) {
  const response = await fetch(url, options);
  let body;
  try {
    body = await response.json();
  } catch {
    throw new Error(`Server returned an unexpected response (${response.status}).`);
  }
  if (!response.ok) throw new Error(body.error || `Request failed (${response.status}).`);
  return body;
}

function coordinateGridSpacing() {
  const zoom = map.getZoom();
  if (zoom >= 17) return 100;
  if (zoom >= 16) return 250;
  if (zoom >= 14) return 500;
  if (zoom >= 12) return 1000;
  if (zoom >= 10) return 2500;
  if (zoom >= 8) return 5000;
  return 10000;
}

async function refreshCoordinateGrid() {
  if (!$("#show-coordinate-grid").checked) return;
  const requestId = ++coordinateGridRequest;
  const bounds = map.getBounds();
  const query = new URLSearchParams({
    west: bounds.getWest(),
    south: bounds.getSouth(),
    east: bounds.getEast(),
    north: bounds.getNorth(),
    spacing: coordinateGridSpacing(),
  });
  try {
    const result = await requestJson(`/api/coordinate-grid?${query}`);
    if (requestId !== coordinateGridRequest || !$("#show-coordinate-grid").checked) return;
    coordinateGridLayer.clearLayers();
    coordinateGridLayer.addData(result);
  } catch (error) {
    if (requestId === coordinateGridRequest) showNotice(error.message);
  }
}

function addPanelPoint(x = "", y = "", focus = false) {
  const row = document.createElement("div");
  row.className = "panel-point";

  const number = document.createElement("span");
  number.className = "panel-point-number";

  const xInput = document.createElement("input");
  xInput.type = "number";
  xInput.step = "any";
  xInput.placeholder = "X";
  xInput.setAttribute("aria-label", "Point X coordinate in metres");
  xInput.dataset.coordinate = "x";
  xInput.value = x;

  const yInput = document.createElement("input");
  yInput.type = "number";
  yInput.step = "any";
  yInput.placeholder = "Y";
  yInput.setAttribute("aria-label", "Point Y coordinate in metres");
  yInput.dataset.coordinate = "y";
  yInput.value = y;

  const remove = document.createElement("button");
  remove.type = "button";
  remove.className = "text-button";
  remove.textContent = "Remove";
  remove.setAttribute("aria-label", "Remove boundary point");

  row.append(number, xInput, yInput, remove);
  $("#panel-points").append(row);
  updatePanelPointNumbers();
  if (focus) xInput.focus();
}

function updatePanelPointNumbers() {
  $("#panel-points").querySelectorAll(".panel-point-number").forEach((number, index) => {
    number.textContent = String(index + 1);
  });
}

function isValidIsoDate(value) {
  if (!value) return true;
  if (!/^\d{4}-\d{2}-\d{2}$/.test(value)) return false;
  const parsed = new Date(`${value}T00:00:00Z`);
  return !Number.isNaN(parsed.getTime()) && parsed.toISOString().slice(0, 10) === value;
}

function bindIsoDatePicker(fieldId, pickerId, onChange = () => {}) {
  const field = $(fieldId);
  const picker = $(pickerId);
  field.addEventListener("input", () => {
    picker.value = isValidIsoDate(field.value) ? field.value : "";
    onChange();
  });
  picker.addEventListener("change", () => {
    field.value = picker.value;
    onChange();
  });
}

function buildPanelDescription() {
  const identifier = $("#panel-identifier").value.trim();
  const buffer = Number($("#panel-buffer").value);
  if (!identifier) throw new Error("Enter a panel name or identifier.");
  if (!$("#panel-buffer").value || !Number.isFinite(buffer) || buffer < 0 || buffer > 100000) {
    throw new Error("Buffer distance must be between 0 and 100,000 metres.");
  }
  const start = $("#panel-start").value;
  const end = $("#panel-end").value;
  if (!isValidIsoDate(start) || !isValidIsoDate(end)) {
    throw new Error("Enter mining dates in YYYY-MM-DD format using valid calendar dates.");
  }
  if (start && end && start > end) throw new Error("Mining start date must not be after the end date.");

  const points = [];
  $("#panel-points").querySelectorAll(".panel-point").forEach((row, index) => {
    const x = row.querySelector('[data-coordinate="x"]').value.trim();
    const y = row.querySelector('[data-coordinate="y"]').value.trim();
    if (!x && !y) return;
    if (!x || !y || !Number.isFinite(Number(x)) || !Number.isFinite(Number(y))) {
      throw new Error(`Enter valid X and Y coordinates for boundary point ${index + 1}.`);
    }
    points.push(`${points.length + 1}, ${x}, ${y}`);
  });
  if (points.length < 3) throw new Error("Enter at least three complete boundary points.");

  const description = [`Porub ${identifier}`, ...points];
  if (start || end) {
    description.push(`Dobývání porubu${start ? ` od ${start}` : ""}${end ? ` do ${end}` : ""}`);
  }
  description.push(`Oblast pro sledování seismicity: plocha ${buffer} m vně obrysu porubu.`);
  return description.join("\n");
}

function invalidatePanelPreview() {
  if (previewDescription === null) return;
  previewDescription = null;
  previewLayer.clearLayers();
}

function panelsForSelectedSeam() {
  const selectedSeam = seamSelect.value;
  return panels.filter((panel) => !selectedSeam || (panel.seam || "").trim() === selectedSeam);
}

function selectPanelById(panelId) {
  const panel = panels.find((item) => String(item.id) === String(panelId));
  if (!panel) return;
  seamSelect.value = (panel.seam || "").trim();
  populatePanelSelect(panel.id);
  selectPanel();
}

function panelBoundaryLayer(panel, style) {
  const label = panel.seam ? `${panel.identifier} · ${panel.seam}` : panel.identifier;
  return L.geoJSON(panel.boundary, {
    style,
    onEachFeature: (_feature, layer) => {
      layer.bindTooltip(label);
      layer.on("click", () => selectPanelById(panel.id));
    },
  });
}

function updateSeamOptions() {
  const selectedSeam = seamSelect.value;
  const seams = [...new Set(panels.map((panel) => (panel.seam || "").trim()).filter(Boolean))]
    .sort((left, right) => left.localeCompare(right));
  seamSelect.replaceChildren();
  const allSeams = document.createElement("option");
  allSeams.value = "";
  allSeams.textContent = "All seams";
  seamSelect.append(allSeams);
  for (const seam of seams) {
    const option = document.createElement("option");
    option.value = seam;
    option.textContent = seam;
    seamSelect.append(option);
  }
  seamSelect.value = seams.includes(selectedSeam) ? selectedSeam : "";
}

function fitPanel(panel) {
  panelLayer.clearLayers();
  let targetBounds = null;
  if (panel) {
    const monitoring = L.geoJSON(panel.monitoring_area, {
      style: { color: "#d68a36", weight: 2, dashArray: "6 5", fillColor: "#e9b675", fillOpacity: 0.12 },
    });
    const boundary = panelBoundaryLayer(panel, {
      color: "#176f86", weight: 3, fillColor: "#52a7af", fillOpacity: 0.13,
    });
    if (!showPanelOutlines.checked) {
      targetBounds = monitoring.getBounds();
    } else {
      panelLayer.addLayer(monitoring);
      panelLayer.addLayer(boundary);
    }
  } else {
    targetBounds = L.latLngBounds();
    for (const item of panelsForSelectedSeam()) {
      const boundary = panelBoundaryLayer(item, {
        color: "#526b78", weight: 2, fillColor: "#526b78", fillOpacity: 0.03,
      });
      targetBounds.extend(boundary.getBounds());
      if (showPanelOutlines.checked) panelLayer.addLayer(boundary);
    }
  }
  const bounds = targetBounds || panelLayer.getBounds();
  if (bounds.isValid()) map.fitBounds(bounds.pad(0.13));
}

function addEventPopup(event, marker) {
  const container = document.createElement("div");
  const heading = document.createElement("strong");
  heading.textContent = event.datetime.replace("T", " ");
  const details = document.createElement("p");
  details.textContent = `Energy: ${formatNumber(event.energy)} · Magnitude: ${formatNumber(event.magnitude)} · Z: ${formatNumber(event.z_m)} m`;
  const raw = document.createElement("pre");
  const attributes = Object.fromEntries(
    Object.entries(event.attributes || {}).map(([name, value]) => [
      name.replace(/^\uFF88tverec/i, "Čtverec").replace(/^ctverec\b/i, "Čtverec").replace(/\s+/g, " ").trim(),
      value,
    ]),
  );
  raw.textContent = JSON.stringify(attributes, null, 2);
  container.append(heading, details, raw);
  marker.bindPopup(container);
}

function magnitudeColor(magnitude, minimum, maximum) {
  if (magnitude === null || magnitude === undefined) return "#6b7280";
  if (minimum === maximum) return "#b91c1c";
  const ratio = Math.max(0, Math.min(1, (magnitude - minimum) / (maximum - minimum)));
  const lightness = 82 - ratio * 42;
  return `hsl(4, 76%, ${lightness}%)`;
}

function drawEvents(events) {
  eventLayer.clearLayers();
  const magnitudes = events.map((e) => e.magnitude).filter((value) => value !== null);
  const minMagnitude = magnitudes.length ? Math.min(...magnitudes) : 0;
  const maxMagnitude = magnitudes.length ? Math.max(...magnitudes) : 0;
  const energies = events.map((e) => e.energy).filter((value) => value > 0);
  const minLogEnergy = energies.length ? Math.log10(Math.min(...energies)) : 0;
  const maxLogEnergy = energies.length ? Math.log10(Math.max(...energies)) : 0;
  for (const event of events) {
    const logEnergy = event.energy > 0 ? Math.log10(event.energy) : minLogEnergy;
    const ratio = maxLogEnergy === minLogEnergy ? 0.5 :
      (logEnergy - minLogEnergy) / (maxLogEnergy - minLogEnergy);
    const marker = L.circleMarker([event.latitude, event.longitude], {
      radius: 4 + ratio * 6,
      color: magnitudeColor(event.magnitude, minMagnitude, maxMagnitude),
      fillOpacity: 0.76,
      weight: 1,
    });
    addEventPopup(event, marker);
    marker.addTo(eventLayer);
  }
}

function updateStatistics(stats) {
  $("#stat-count").textContent = formatNumber(stats.count, 0);
  $("#stat-energy").textContent = formatNumber(stats.total_energy);
  $("#stat-mean").textContent = formatNumber(stats.mean_magnitude);
  $("#stat-max-mag").textContent = formatNumber(stats.max_magnitude);
  $("#stat-max-energy").textContent = formatNumber(stats.max_energy);
  $("#chart-empty").textContent = stats.count ? "" : "No events match this panel and filter selection.";
  if (energyChart) energyChart.destroy();
  if (timeChart) timeChart.destroy();
  energyChart = new Chart($("#energy-chart"), {
    type: "bar",
    data: {
      labels: stats.energy_distribution.map((item) => item.bin),
      datasets: [{ label: "Events", data: stats.energy_distribution.map((item) => item.count), backgroundColor: "#4b9ba0" }],
    },
    options: { responsive: true, maintainAspectRatio: false, scales: { y: { beginAtZero: true, ticks: { precision: 0 } } }, plugins: { legend: { display: false } } },
  });
  timeChart = new Chart($("#time-chart"), {
    type: "bar",
    data: {
      labels: stats.timeline.map((item) => item.month.slice(0, 7)),
      datasets: [
        { label: "Events / month", data: stats.timeline.map((item) => item.count), backgroundColor: "#77aeb2", yAxisID: "events" },
        { type: "line", label: "Cumulative energy", data: stats.timeline.map((item) => item.cumulative_energy), borderColor: "#d2743b", backgroundColor: "#d2743b", pointRadius: 1, yAxisID: "energy" },
      ],
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      scales: {
        events: { beginAtZero: true, position: "left", ticks: { precision: 0 } },
        energy: { beginAtZero: true, position: "right", grid: { drawOnChartArea: false } },
      },
    },
  });
}

function filterQuery() {
  const panelId = panelSelect.value;
  if (!panelId) throw new Error("Select a mining panel first.");
  const query = new URLSearchParams({ panel_id: panelId, period: $("#period").value });
  if ($("#period").value === "range") {
    const start = $("#start-date").value;
    const end = $("#end-date").value;
    if (!start || !end) throw new Error("Choose both dates for the custom interval.");
    if (!isValidIsoDate(start) || !isValidIsoDate(end)) {
      throw new Error("Enter filter dates in YYYY-MM-DD format using valid calendar dates.");
    }
    if (start > end) throw new Error("From date must not be after To date.");
    query.set("start", start);
    query.set("end", end);
  }
  if ($("#min-energy").value) query.set("min_energy", $("#min-energy").value);
  if ($("#min-magnitude").value) query.set("min_magnitude", $("#min-magnitude").value);
  return query;
}

async function applyFilters() {
  clearNotice();
  try {
    const query = filterQuery();
    const [events, stats] = await Promise.all([
      requestJson(`/api/events?${query}`),
      requestJson(`/api/statistics?${query}`),
    ]);
    drawEvents(events.events);
    updateStatistics(stats);
    $("#event-count").textContent = `${formatNumber(stats.count, 0)} matching events · ${formatNumber(events.returned, 0)} shown${events.truncated ? ` (map limited to ${formatNumber(events.limit, 0)})` : ""}`;
  } catch (error) {
    showNotice(error.message);
  }
}

function populatePanelSelect(selectedId = null) {
  const visiblePanels = panelsForSelectedSeam();
  panelSelect.replaceChildren();
  const placeholder = document.createElement("option");
  placeholder.value = "";
  placeholder.textContent = visiblePanels.length
    ? "Choose a panel…"
    : panels.length
      ? "No panels in this seam"
      : "No panels defined";
  panelSelect.append(placeholder);
  for (const panel of visiblePanels) {
    const option = document.createElement("option");
    option.value = panel.id;
    option.textContent = panel.seam ? `${panel.identifier} · ${panel.seam}` : panel.identifier;
    panelSelect.append(option);
  }
  const requestedPanel = visiblePanels.find((panel) => String(panel.id) === String(selectedId));
  panelSelect.value = requestedPanel ? String(requestedPanel.id) : "";
}

async function loadPanels(selectedId = null) {
  panels = await requestJson("/api/panels");
  updateSeamOptions();
  const selectedPanel = selectedId
    ? panels.find((panel) => String(panel.id) === String(selectedId))
    : null;
  if (selectedId && selectedPanel) seamSelect.value = (selectedPanel.seam || "").trim();
  const visiblePanels = panelsForSelectedSeam();
  const defaultPanel = visiblePanels.find((panel) => panel.identifier === "138 708") || visiblePanels[0];
  populatePanelSelect(selectedPanel ? selectedPanel.id : defaultPanel ? defaultPanel.id : null);
  selectPanel();
}

function selectPanel() {
  const panel = panels.find((item) => String(item.id) === panelSelect.value);
  fitPanel(panel);
  $("#panel-summary").textContent = panel
    ? `Monitoring boundary: ${formatNumber(panel.buffer_m, 0)} m buffer · Mining: ${panel.mining_start || "not set"} to ${panel.mining_end || "not set"}`
    : "";
  eventLayer.clearLayers();
  if (panel) applyFilters();
  else {
    const visiblePanels = panelsForSelectedSeam();
    $("#event-count").textContent = !panels.length
      ? "No panels defined."
      : !showPanelOutlines.checked
        ? "No panel selected · panel outlines hidden."
        : `No panel selected · showing ${formatNumber(visiblePanels.length, 0)} panel outline${visiblePanels.length === 1 ? "" : "s"}${seamSelect.value ? ` for ${seamSelect.value}` : ""}.`;
    updateStatistics({ count: 0, total_energy: 0, mean_magnitude: null, max_magnitude: null, max_energy: null, energy_distribution: [], timeline: [] });
    $("#chart-empty").textContent = panels.length
      ? "Select a panel to view event statistics."
      : "Create a mining panel to explore events.";
  }
}

async function previewPanel() {
  clearNotice();
  previewDescription = null;
  previewLayer.clearLayers();
  try {
    const description = buildPanelDescription();
    const preview = await requestJson("/api/panels/preview", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ description, seam: $("#panel-seam").value }),
    });
    L.geoJSON(preview.monitoring_geojson, {
      style: { color: "#d68a36", weight: 2, dashArray: "6 5", fillColor: "#e9b675", fillOpacity: 0.12 },
    }).addTo(previewLayer);
    L.geoJSON(preview.boundary_geojson, {
      style: { color: "#176f86", weight: 3, fillColor: "#52a7af", fillOpacity: 0.13 },
    }).addTo(previewLayer);
    const bounds = previewLayer.getBounds();
    if (bounds.isValid()) {
      map.invalidateSize();
      map.fitBounds(bounds.pad(0.13));
      $("#map").scrollIntoView({ behavior: "smooth", block: "center" });
    }
    previewDescription = description;
    $("#save-panel").textContent = editingId ? "Update panel" : "Save panel";
  } catch (error) {
    showNotice(error.message);
  }
}

function clearEditor() {
  editingId = null;
  originalDescription = null;
  previewDescription = null;
  previewLayer.clearLayers();
  $("#panel-identifier").value = "";
  $("#panel-seam").value = "";
  $("#panel-start").value = "";
  $("#panel-end").value = "";
  $("#panel-start-picker").value = "";
  $("#panel-end-picker").value = "";
  $("#panel-buffer").value = "100";
  $("#panel-points").replaceChildren();
  for (let point = 0; point < 3; point += 1) addPanelPoint();
  $("#save-panel").textContent = "Save panel";
  $("#cancel-edit").classList.add("hidden");
}

async function savePanel() {
  const method = editingId ? "PUT" : "POST";
  const url = editingId ? `/api/panels/${editingId}` : "/api/panels";
  try {
    const description = buildPanelDescription();
    const saved = await requestJson(url, {
      method,
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        description,
        seam: $("#panel-seam").value,
        ...(editingId ? { original_description: originalDescription } : {}),
      }),
    });
    clearEditor();
    await loadPanels(saved.id);
    clearNotice();
  } catch (error) {
    showNotice(error.message);
  }
}

async function editPanel() {
  const panelId = panelSelect.value;
  if (!panelId) return showNotice("Select a panel to edit.");
  try {
    const panel = await requestJson(`/api/panels/${panelId}`);
    $("#panel-management").open = true;
    editingId = panel.id;
    originalDescription = panel.description;
    $("#panel-identifier").value = panel.identifier;
    $("#panel-seam").value = panel.seam || "";
    $("#panel-start").value = panel.mining_start || "";
    $("#panel-end").value = panel.mining_end || "";
    $("#panel-start-picker").value = panel.mining_start || "";
    $("#panel-end-picker").value = panel.mining_end || "";
    $("#panel-buffer").value = panel.buffer_m;
    $("#panel-points").replaceChildren();
    for (const [x, y] of panel.vertices) addPanelPoint(x, y);
    $("#cancel-edit").classList.remove("hidden");
    await previewPanel();
  } catch (error) {
    showNotice(error.message);
  }
}

async function deletePanel() {
  const panelId = panelSelect.value;
  const panel = panels.find((item) => String(item.id) === panelId);
  if (!panel || !window.confirm(`Delete panel ${panel.identifier}?`)) return;
  try {
    await requestJson(`/api/panels/${panelId}`, { method: "DELETE" });
    await loadPanels();
    clearNotice();
  } catch (error) {
    showNotice(error.message);
  }
}

async function importWorkbook(event) {
  event.preventDefault();
  const file = $("#import-file").files[0];
  if (!file) return;
  const result = $("#import-result");
  result.textContent = "Importing workbook…";
  const form = new FormData($("#import-form"));
  try {
    const stats = await requestJson("/api/import", { method: "POST", body: form });
    const parts = [
      stats.already_imported ? "This exact file was already imported." : `Imported ${stats.filename} (${stats.source_type}).`,
      `${stats.accepted_rows} accepted`,
      `${stats.skipped_rows} skipped`,
      `${stats.duplicate_events} duplicate events`,
      `${stats.warnings} warnings`,
    ];
    result.textContent = parts.join(" · ");
    if (stats.issues && stats.issues.length) {
      const list = document.createElement("ul");
      list.className = "issue-list";
      for (const issue of stats.issues) {
        const item = document.createElement("li");
        item.textContent = `Row ${issue.row}: ${issue.message}`;
        list.append(item);
      }
      result.append(list);
    }
    if (panelSelect.value) applyFilters();
  } catch (error) {
    result.textContent = error.message;
  }
}

$("#period").addEventListener("change", () => $("#date-range").classList.toggle("hidden", $("#period").value !== "range"));
$("#apply-filters").addEventListener("click", applyFilters);
panelSelect.addEventListener("change", selectPanel);
seamSelect.addEventListener("change", () => {
  const selectedPanelId = panelSelect.value;
  populatePanelSelect(selectedPanelId);
  selectPanel();
});
showPanelOutlines.addEventListener("change", () => {
  const panel = panels.find((item) => String(item.id) === panelSelect.value);
  fitPanel(panel);
  if (!panel) {
    const visiblePanels = panelsForSelectedSeam();
    $("#event-count").textContent = !showPanelOutlines.checked
      ? "No panel selected · panel outlines hidden."
      : `No panel selected · showing ${formatNumber(visiblePanels.length, 0)} panel outline${visiblePanels.length === 1 ? "" : "s"}${seamSelect.value ? ` for ${seamSelect.value}` : ""}.`;
  }
});
panelSelect.addEventListener("change", () => {
  if (editingId && String(editingId) !== panelSelect.value) clearEditor();
});
$("#preview-panel").addEventListener("click", previewPanel);
$("#save-panel").addEventListener("click", savePanel);
$("#cancel-edit").addEventListener("click", clearEditor);
$("#new-panel").addEventListener("click", () => {
  clearEditor();
  $("#panel-management").open = true;
  $("#panel-identifier").focus();
});
$("#clear-panel-selection").addEventListener("click", () => {
  if (editingId) {
    showNotice("Save or cancel panel editing before clearing the selection.");
    return;
  }
  clearNotice();
  panelSelect.value = "";
  selectPanel();
});
$("#import-form").addEventListener("submit", importWorkbook);
for (const selector of ["#panel-identifier", "#panel-seam", "#panel-buffer"]) {
  $(selector).addEventListener("input", invalidatePanelPreview);
}
for (const [fieldId, pickerId] of [
  ["#panel-start", "#panel-start-picker"],
  ["#panel-end", "#panel-end-picker"],
  ["#start-date", "#start-date-picker"],
  ["#end-date", "#end-date-picker"],
]) {
  bindIsoDatePicker(fieldId, pickerId, fieldId.startsWith("#panel-") ? invalidatePanelPreview : undefined);
}
document.querySelectorAll(".calendar-picker-trigger").forEach((button) => {
  button.addEventListener("click", () => {
    const picker = document.getElementById(button.dataset.picker);
    if (typeof picker.showPicker === "function") picker.showPicker();
    else picker.click();
  });
});
$("#panel-points").addEventListener("input", invalidatePanelPreview);
$("#panel-points").addEventListener("click", (event) => {
  if (!event.target.matches(".text-button")) return;
  event.target.closest(".panel-point").remove();
  updatePanelPointNumbers();
  invalidatePanelPreview();
});
$("#add-panel-point").addEventListener("click", () => {
  addPanelPoint("", "", true);
  invalidatePanelPreview();
});
$("#show-coordinate-grid").addEventListener("change", (event) => {
  coordinateGridRequest += 1;
  if (event.target.checked) {
    map.addLayer(coordinateGridLayer);
    refreshCoordinateGrid();
  } else {
    coordinateGridLayer.clearLayers();
    map.removeLayer(coordinateGridLayer);
  }
});
map.on("moveend", refreshCoordinateGrid);

document.querySelectorAll(".edit-selected").forEach((button) => button.addEventListener("click", editPanel));
document.querySelectorAll(".delete-selected").forEach((button) => button.addEventListener("click", deletePanel));

for (let point = 0; point < 3; point += 1) addPanelPoint();
loadPanels().catch((error) => showNotice(error.message));
