/**
 * CONVRAIN Precision Satellite Convective Nowcasting Platform
 * UI/UX & Frontend Architecture Controller (SpaceX + Apple + Windy)
 * Zero-Page-Scroll Heads-Up Display (HUD)
 */

(function () {
  "use strict";

  // --------------------------------------------------------------------------
  // Application State
  // --------------------------------------------------------------------------
  const state = {
    scans: [],
    currentScanIndex: 0,
    currentStamp: null,
    scanData: null,
    selectedTrackId: null,
    selectedPoint: { lat: 13.7563, lon: 100.5018 },
    isPlaying: false,
    playIntervalId: null,
    playSpeedMs: 1800,
    viewMode: "operational", // "operational" | "physics"
    layers: {
      irHeat: true,
      footprints: true,
      parallax: true,
      motion: true,
      rawSatellite: false,
      warningOnly: false,
      compareParallax: false,
    },
  };

  // --------------------------------------------------------------------------
  // DOM References
  // --------------------------------------------------------------------------
  const dom = {
    // Zone A
    telemetryBar: document.getElementById("telemetry-bar"),
    telSatBand: document.getElementById("tel-sat-band"),
    telScanTime: document.getElementById("tel-scan-time"),
    telLatency: document.getElementById("tel-latency"),
    telActiveCells: document.getElementById("tel-active-cells"),
    telWarnings: document.getElementById("tel-warnings"),
    btnToggleViewMode: document.getElementById("btn-toggle-view-mode"),
    lblViewMode: document.getElementById("lbl-view-mode"),

    // Zone B Map & Search
    mapContainer: document.getElementById("map"),
    coordSearchInput: document.getElementById("coord-search-input"),
    btnSearchCoords: document.getElementById("btn-search-coords"),
    btnMyGps: document.getElementById("btn-my-gps"),
    presetChips: document.querySelectorAll(".preset-location-chips .chip"),

    // Zone E Layers
    btnLayerIr: document.getElementById("btn-layer-ir"),
    btnLayerFootprints: document.getElementById("btn-layer-footprints"),
    btnLayerParallax: document.getElementById("btn-layer-parallax"),
    btnLayerMotion: document.getElementById("btn-layer-motion"),
    btnFilterWarning: document.getElementById("btn-filter-warning"),
    btnCompareParallax: document.getElementById("btn-compare-parallax"),

    // Zone C Inspector Drawer
    inspectorDrawer: document.getElementById("inspector-drawer"),
    btnCloseInspector: document.getElementById("btn-close-inspector"),
    inspCoordVal: document.getElementById("insp-coord-val"),
    inspHeroCard: document.getElementById("insp-hero-card"),
    inspStatusBadge: document.getElementById("insp-status-badge"),
    inspConfBadge: document.getElementById("insp-conf-badge"),
    inspHeadline: document.getElementById("insp-headline"),
    inspConfBar: document.getElementById("insp-conf-bar"),
    inspEtaSub: document.getElementById("insp-eta-sub"),
    inspTrackId: document.getElementById("insp-track-id"),
    inspShiftDesc: document.getElementById("insp-shift-desc"),
    inspTbMin: document.getElementById("insp-tb-min"),
    inspTbC: document.getElementById("insp-tb-c"),
    inspCoolingRate: document.getElementById("insp-cooling-rate"),
    inspAreaGrowth: document.getElementById("insp-area-growth"),
    inspAreaTotal: document.getElementById("insp-area-total"),
    inspVelocity: document.getElementById("insp-velocity"),
    inspDirection: document.getElementById("insp-direction"),
    inspDirDeg: document.getElementById("insp-dir-deg"),
    microChartSvg: document.getElementById("micro-chart-svg"),
    chartTooltip: document.getElementById("chart-tooltip"),
    chartTimeStart: document.getElementById("chart-time-start"),
    chartTimeEnd: document.getElementById("chart-time-end"),
    btnExportCsv: document.getElementById("btn-export-csv"),
    btnTrackLog: document.getElementById("btn-track-log"),

    // Zone D Timeline Scrubber
    btnTimelinePrev: document.getElementById("btn-timeline-prev"),
    btnTimelinePlay: document.getElementById("btn-timeline-play"),
    btnTimelineNext: document.getElementById("btn-timeline-next"),
    timelineScrubber: document.getElementById("timeline-scrubber"),
    sliderStampDisplay: document.getElementById("slider-stamp-display"),
    sliderStepDesc: document.getElementById("slider-step-desc"),
    sliderModeBadge: document.getElementById("slider-mode-badge"),
    lblNowMarker: document.getElementById("lbl-now-marker"),
    speedButtons: document.querySelectorAll(".speed-btn"),

    // Mission Control Modal
    missionControlModal: document.getElementById("mission-control-modal"),
    btnCloseModal: document.getElementById("btn-close-modal"),
    modalTotalLatency: document.getElementById("modal-total-latency"),
    modalActiveTracks: document.getElementById("modal-active-tracks"),
    modalOnsetWarnings: document.getElementById("modal-onset-warnings"),
    modalBoundaryStatus: document.getElementById("modal-boundary-status"),
    stagesBarsContainer: document.getElementById("stages-bars-container"),
    boundaryLogTerminal: document.getElementById("boundary-log-terminal"),
  };

  // --------------------------------------------------------------------------
  // Map Engine (Leaflet with Deep Obsidian Tiles)
  // --------------------------------------------------------------------------
  let map;
  let layerFootprints = L.layerGroup();
  let layerRawFootprints = L.layerGroup();
  let layerParallaxVectors = L.layerGroup();
  let layerMotionVectors = L.layerGroup();
  let layerReticle = L.layerGroup();

  function initMap() {
    map = L.map("map", {
      center: [14.5, 101.0],
      zoom: 7,
      minZoom: 4,
      maxZoom: 16,
      zoomControl: false,
      attributionControl: false,
      preferCanvas: true,
    });

    // Create high-z-index pane for crisp labels and city names
    map.createPane("labelsPane");
    map.getPane("labelsPane").style.zIndex = "650";
    map.getPane("labelsPane").style.pointerEvents = "none";

    // 1. High-Tech Dark Gray Canvas Base Map (Esri Canvas World Dark Gray)
    const baseDark = L.tileLayer(
      "https://server.arcgisonline.com/ArcGIS/rest/services/Canvas/World_Dark_Gray_Base/MapServer/tile/{z}/{y}/{x}",
      {
        maxZoom: 16,
      }
    );

    // 2. High-Tech Reference Labels & Boundary Lines (Sits above weather data in labelsPane)
    const refLabels = L.tileLayer(
      "https://server.arcgisonline.com/ArcGIS/rest/services/Canvas/World_Dark_Gray_Reference/MapServer/tile/{z}/{y}/{x}",
      {
        pane: "labelsPane",
        maxZoom: 16,
      }
    );

    baseDark.addTo(map);
    refLabels.addTo(map);

    // Add layer groups to map
    layerRawFootprints.addTo(map);
    layerParallaxVectors.addTo(map);
    layerFootprints.addTo(map);
    layerMotionVectors.addTo(map);
    layerReticle.addTo(map);

    // Ensure map tiles calculate correct container dimensions
    setTimeout(() => {
      if (map) map.invalidateSize();
    }, 150);

    // Map Click -> Trigger Pinpoint Nowcast Reticle
    map.on("click", (e) => {
      const lat = parseFloat(e.latlng.lat.toFixed(4));
      const lon = parseFloat(e.latlng.lng.toFixed(4));
      lockTargetReticle(lat, lon);
    });
  }

  // --------------------------------------------------------------------------
  // SpaceX Target Reticle & Concentric Risk Rings
  // --------------------------------------------------------------------------
  function lockTargetReticle(lat, lon) {
    state.selectedPoint = { lat, lon };
    dom.coordSearchInput.value = `${lat}, ${lon}`;
    dom.inspCoordVal.textContent = `LAT: ${lat} | LON: ${lon}`;

    layerReticle.clearLayers();

    // 1. Concentric Risk Rings (5 km and 10 km Earth Tone)
    const ring5km = L.circle([lat, lon], {
      radius: 5000,
      color: "rgba(212, 106, 76, 0.55)",
      weight: 1,
      dashArray: "4, 6",
      fill: true,
      fillColor: "rgba(212, 106, 76, 0.08)",
      interactive: false,
    });

    const ring10km = L.circle([lat, lon], {
      radius: 10000,
      color: "rgba(201, 168, 124, 0.45)",
      weight: 1,
      dashArray: "6, 8",
      fill: true,
      fillColor: "rgba(201, 168, 124, 0.04)",
      interactive: false,
    });

    ring5km.addTo(layerReticle);
    ring10km.addTo(layerReticle);

    // 2. Animated SpaceX Radar Reticle Icon
    const reticleHtml = `
      <div class="spacex-reticle-container">
        <div class="reticle-outer-ring"></div>
        <div class="reticle-inner-ring"></div>
        <div class="reticle-crosshair-h"></div>
        <div class="reticle-crosshair-v"></div>
        <div class="reticle-center-dot"></div>
        <div class="reticle-risk-label">LOCK [${lat}, ${lon}]</div>
      </div>
    `;

    const reticleIcon = L.divIcon({
      className: "custom-reticle-icon",
      html: reticleHtml,
      iconSize: [90, 90],
      iconAnchor: [45, 45],
    });

    L.marker([lat, lon], { icon: reticleIcon, interactive: false }).addTo(layerReticle);

    // 3. Trigger Point Nowcast API Call
    fetchPointNowcast(lat, lon);
  }

  // --------------------------------------------------------------------------
  // Data Fetching: Point Nowcast & Inspector Drawer
  // --------------------------------------------------------------------------
  async function fetchPointNowcast(lat, lon) {
    try {
      const stampParam = state.currentStamp ? `&stamp=${state.currentStamp}` : "";
      const res = await fetch(`/api/nowcast/point?lat=${lat}&lon=${lon}${stampParam}`);
      if (!res.ok) throw new Error("Point nowcast failed");
      const data = await res.json();
      renderInspector(data);
    } catch (err) {
      console.error("[Nowcast] Error:", err);
    }
  }

  function renderInspector(data) {
    dom.inspectorDrawer.classList.add("open");

    // Status & Severity Badge
    const severity = data.severity || "NORMAL";
    dom.inspStatusBadge.className = "status-pill";
    if (severity === "CRIMSON_WARNING") {
      dom.inspStatusBadge.classList.add("status-warning");
      dom.inspStatusBadge.textContent = "RAINFALL ONSET WARNING";
      dom.inspConfBar.style.background = "linear-gradient(90deg, #D99B52, #D46A4C)";
    } else if (severity === "CONVECTIVE_WATCH" || severity === "DEVELOPING") {
      dom.inspStatusBadge.classList.add("status-watch");
      dom.inspStatusBadge.textContent = "CONVECTIVE WATCH";
      dom.inspConfBar.style.background = "linear-gradient(90deg, #7E9AA8, #D99B52)";
    } else {
      dom.inspStatusBadge.classList.add("status-clear");
      dom.inspStatusBadge.textContent = "SAFE / CLEAR AIR";
      dom.inspConfBar.style.background = "#7FA073";
    }

    // Headline & Confidence
    dom.inspHeadline.textContent = data.headline || "ตรวจวัดสภาพอากาศสำเร็จ";
    dom.inspConfBadge.textContent = `Confidence: ${data.confidence_score}%`;
    dom.inspConfBar.style.width = `${data.confidence_score}%`;

    const distText = data.distance_km !== null ? ` | ระยะห่างจากแกนเมฆ: ${data.distance_km} กม.` : "";
    dom.inspEtaSub.textContent = `เวลาท้องถิ่นไทย: ${data.eta_time_thai} (${data.eta_time_utc})${distText}`;

    // Track Physics & Parallax Badge
    const track = data.track;
    if (track) {
      state.selectedTrackId = track.object_id;
      dom.inspTrackId.textContent = `Track ID: ${track.track_id || track.object_id}`;
      dom.inspShiftDesc.innerHTML = `ปรับแก้พิกัดตกกระทบพื้นดิน: <strong>${track.parallax_shift_km} km ${track.parallax_bearing}</strong> (True Ground Footprint)`;

      // Bento 4 Metrics
      dom.inspTbMin.textContent = `${track.min_bt} K`;
      dom.inspTbC.textContent = `(${track.min_bt_c} °C)`;
      dom.inspCoolingRate.textContent = `${track.cooling_rate} K/min`;
      dom.inspAreaGrowth.textContent = `${track.area_growth >= 0 ? "+" : ""}${track.area_growth} km²`;
      dom.inspAreaTotal.textContent = `${track.area_km2} km²`;
      dom.inspVelocity.textContent = `${track.speed_kmh} km/h`;
      dom.inspDirection.textContent = `➔ ${track.compass_dir}`;
      dom.inspDirDeg.textContent = `${track.direction_deg}° (${track.compass_thai || track.compass_dir})`;
    } else {
      state.selectedTrackId = null;
      dom.inspTrackId.textContent = "Track ID: N/A";
      dom.inspShiftDesc.textContent = "ไม่พบกลุ่มเมฆพาความร้อนในรัศมีเฝ้าระวัง 45 กม.";
      dom.inspTbMin.textContent = "-- K";
      dom.inspTbC.textContent = "(-- °C)";
      dom.inspCoolingRate.textContent = "0.0 K/min";
      dom.inspAreaGrowth.textContent = "0 km²";
      dom.inspAreaTotal.textContent = "0 km²";
      dom.inspVelocity.textContent = "0 km/h";
      dom.inspDirection.textContent = "-";
      dom.inspDirDeg.textContent = "-";
    }

    // Render Micro-Timeseries Chart
    renderMicroTimeseries(data.track_history || []);
  }

  // --------------------------------------------------------------------------
  // Micro-Timeseries SVG Chart (Tb vs Onset Probability)
  // --------------------------------------------------------------------------
  function renderMicroTimeseries(history) {
    const svg = dom.microChartSvg;
    svg.innerHTML = "";

    if (!history || history.length < 2) {
      svg.innerHTML = `
        <text x="190" y="70" text-anchor="middle" fill="#64748B" font-size="11" font-family="var(--font-mono)">
          ไม่มีข้อมูลย้อนหลังเพียงพอสำหรับพล็อตกราฟ (ตรวจพบเซลล์ใหม่)
        </text>
      `;
      dom.chartTimeStart.textContent = "--:--";
      dom.chartTimeEnd.textContent = "--:--";
      return;
    }

    const n = history.length;
    dom.chartTimeStart.textContent = history[0].time_short;
    dom.chartTimeEnd.textContent = history[n - 1].time_short;

    const width = 380;
    const height = 130;
    const padX = 25;
    const padY = 15;
    const plotW = width - padX * 2;
    const plotH = height - padY * 2;

    // Scales:
    // Tb: 190 K to 280 K (y inverted, lower Tb is higher on the chart!)
    const minTb = 195;
    const maxTb = 275;
    const getY_Tb = (tb) => padY + ((tb - minTb) / (maxTb - minTb)) * plotH;

    // Prob: 0% to 100% (y inverted, 100% is top!)
    const getY_Prob = (p) => padY + (1.0 - p / 100.0) * plotH;

    const getX = (idx) => padX + (idx / (n - 1)) * plotW;

    // Background Grid lines
    let gridHtml = `
      <defs>
        <linearGradient id="gradTb" x1="0%" y1="0%" x2="100%" y2="0%">
          <stop offset="0%" stop-color="#7E9AA8" />
          <stop offset="100%" stop-color="#A5BDC9" />
        </linearGradient>
        <linearGradient id="gradProb" x1="0%" y1="0%" x2="100%" y2="0%">
          <stop offset="0%" stop-color="#D99B52" />
          <stop offset="100%" stop-color="#D46A4C" />
        </linearGradient>
      </defs>
      <line x1="${padX}" y1="${padY}" x2="${width - padX}" y2="${padY}" stroke="rgba(226, 218, 204, 0.06)" stroke-width="1" />
      <line x1="${padX}" y1="${padY + plotH / 2}" x2="${width - padX}" y2="${padY + plotH / 2}" stroke="rgba(226, 218, 204, 0.06)" stroke-width="1" />
      <line x1="${padX}" y1="${padY + plotH}" x2="${width - padX}" y2="${padY + plotH}" stroke="rgba(226, 218, 204, 0.06)" stroke-width="1" />
    `;

    // 50% Threshold horizontal dashed line
    const y50 = getY_Prob(50);
    gridHtml += `
      <line x1="${padX}" y1="${y50}" x2="${width - padX}" y2="${y50}" stroke="rgba(217, 155, 82, 0.45)" stroke-width="1" stroke-dasharray="4, 4" />
      <text x="${width - padX}" y="${y50 - 3}" text-anchor="end" fill="#D99B52" font-size="8" font-family="var(--font-mono)">50% THRESHOLD</text>
    `;

    // Build Path for Tb
    let dTb = "";
    let dProb = "";
    history.forEach((pt, idx) => {
      const x = getX(idx);
      const yTb = getY_Tb(pt.min_bt);
      const yProb = getY_Prob(pt.onset_prob);
      if (idx === 0) {
        dTb += `M ${x} ${yTb}`;
        dProb += `M ${x} ${yProb}`;
      } else {
        dTb += ` L ${x} ${yTb}`;
        dProb += ` L ${x} ${yProb}`;
      }
    });

    let pathsHtml = `
      <path d="${dTb}" fill="none" stroke="url(#gradTb)" stroke-width="2.5" stroke-linecap="round" />
      <path d="${dProb}" fill="none" stroke="url(#gradProb)" stroke-width="2" stroke-linecap="round" />
    `;

    // Data points & hover circles
    let dotsHtml = "";
    history.forEach((pt, idx) => {
      const x = getX(idx);
      const yTb = getY_Tb(pt.min_bt);
      const yProb = getY_Prob(pt.onset_prob);
      dotsHtml += `
        <circle cx="${x}" cy="${yTb}" r="3.5" fill="#7E9AA8" stroke="#121312" stroke-width="1.5" />
        <circle cx="${x}" cy="${yProb}" r="3" fill="#D46A4C" stroke="#121312" stroke-width="1.5" />
      `;
    });

    svg.innerHTML = gridHtml + pathsHtml + dotsHtml;
  }

  // =====================================================================
  // Chaikin's Corner Cutting Algorithm for Natural Organic Cloud Contours
  // =====================================================================
  function chaikinSmoothRing(ring, iterations = 2) {
    if (!ring || ring.length < 3) return ring;
    let current = ring;
    const isClosed = (
      Math.abs(current[0][0] - current[current.length - 1][0]) < 1e-6 &&
      Math.abs(current[0][1] - current[current.length - 1][1]) < 1e-6
    );
    let pts = isClosed ? current.slice(0, -1) : current.slice();
    if (pts.length < 3) return ring;

    for (let it = 0; it < iterations; it++) {
      const smoothed = [];
      const len = pts.length;
      for (let i = 0; i < len; i++) {
        const p0 = pts[i];
        const p1 = pts[(i + 1) % len];
        smoothed.push([
          0.75 * p0[0] + 0.25 * p1[0],
          0.75 * p0[1] + 0.25 * p1[1],
        ]);
        smoothed.push([
          0.25 * p0[0] + 0.75 * p1[0],
          0.25 * p0[1] + 0.75 * p1[1],
        ]);
      }
      pts = smoothed;
    }
    if (isClosed) {
      pts.push([pts[0][0], pts[0][1]]);
    }
    return pts;
  }

  function smoothGeometry(geom, iterations = 2) {
    if (!geom || !geom.coordinates) return geom;
    if (geom.type === "Polygon") {
      return {
        type: "Polygon",
        coordinates: geom.coordinates.map((ring) => chaikinSmoothRing(ring, iterations)),
      };
    } else if (geom.type === "MultiPolygon") {
      return {
        type: "MultiPolygon",
        coordinates: geom.coordinates.map((poly) =>
          poly.map((ring) => chaikinSmoothRing(ring, iterations))
        ),
      };
    }
    return geom;
  }

  // --------------------------------------------------------------------------
  // Map Layer Rendering: Footprints, Parallax Vectors, Motion
  // --------------------------------------------------------------------------
  function renderMapLayers(data) {
    layerFootprints.clearLayers();
    layerRawFootprints.clearLayers();
    layerParallaxVectors.clearLayers();
    layerMotionVectors.clearLayers();

    if (!data) return;

    // 1. Ground Footprints Layer (True Ground Impact with Chaikin Smoothing)
    if (state.layers.footprints && data.footprints && data.footprints.features) {
      data.footprints.features.forEach((feat) => {
        const props = feat.properties;
        if (state.layers.warningOnly && !props.warning) {
          return;
        }

        // Earth Tone Color Spectrum based on temperature and warning
        let fillColor = "#4A6B82"; // Mineral River Slate
        let strokeColor = "#7E9AA8";
        let fillOpacity = 0.55;

        if (props.warning) {
          fillColor = "#D46A4C"; // Burnt Terracotta
          strokeColor = "#E08365";
          fillOpacity = 0.68;
        } else if (props.min_bt < 210) {
          fillColor = "#8D4E5B"; // Clay Wine / Deep Plum
          strokeColor = "#D99B52"; // Warm Ochre
        } else if (props.min_bt < 230) {
          fillColor = "#6B5B75"; // Muted Slate Mauve
          strokeColor = "#8EAEBA"; // River Slate
        } else if (props.status === "developing") {
          fillColor = "#C98E4B"; // Sandstone Amber
          strokeColor = "#D99B52";
        }

        const smoothedFeat = {
          ...feat,
          geometry: smoothGeometry(feat.geometry, 2),
        };

        const geo = L.geoJSON(smoothedFeat, {
          style: {
            color: strokeColor,
            weight: props.warning ? 2 : 1.2,
            fillColor: fillColor,
            fillOpacity: fillOpacity,
            className: props.warning ? "convective-footprint-pulse" : "convective-footprint",
          },
        });

        // Hover & Click interaction
        geo.on("click", (e) => {
          L.DomEvent.stopPropagation(e);
          lockTargetReticle(props.pc_lat, props.pc_lon);
        });

        geo.bindTooltip(
          `
          <div style="font-family:var(--font-mono); font-size:11px;">
            <strong style="color:var(--cyan-telemetry);">${props.track_id}</strong><br>
            Tb Min: <strong>${props.min_bt} K (${props.min_bt_c} °C)</strong><br>
            Cooling: <strong>${props.cooling_rate} K/min</strong><br>
            Parallax Shift: <strong>${props.parallax_shift_km} km ${props.parallax_bearing}</strong><br>
            Onset Prob: <strong>${Math.round(props.p30 * 100)}%</strong>
          </div>
          `,
          { sticky: true, className: "hud-tooltip" }
        );

        geo.addTo(layerFootprints);
      });
    }

    // 2. Raw Satellite Footprints Layer (Dashed gray outline)
    if ((state.layers.rawSatellite || state.layers.compareParallax) && data.raw_footprints && data.raw_footprints.features) {
      data.raw_footprints.features.forEach((feat) => {
        const props = feat.properties;
        if (state.layers.warningOnly && !props.warning) return;

        const smoothedFeat = {
          ...feat,
          geometry: smoothGeometry(feat.geometry, 2),
        };

        L.geoJSON(smoothedFeat, {
          style: {
            color: "rgba(226, 218, 204, 0.45)",
            weight: 1.2,
            dashArray: "4, 5",
            fill: false,
            interactive: false,
          },
        }).addTo(layerRawFootprints);
      });
    }

    // 3. Parallax Displacement Vectors (River Slate line connecting raw -> corrected)
    if (state.layers.parallax && data.parallax_vectors && data.parallax_vectors.features) {
      data.parallax_vectors.features.forEach((feat) => {
        const props = feat.properties;
        const line = L.geoJSON(feat, {
          style: {
            color: "rgba(142, 174, 186, 0.75)",
            weight: 1.5,
            dashArray: "2, 3",
          },
        });

        line.bindTooltip(
          `<span style="font-family:var(--font-mono); font-size:10px; color:#8EAEBA;">${props.shift_km} km ${props.bearing}</span>`,
          { sticky: true, className: "hud-tooltip" }
        );
        line.addTo(layerParallaxVectors);
      });
    }

    // 4. Motion Vector Trajectories (Warm Sandstone Arrows & Cones)
    if (state.layers.motion && data.motion_vectors && data.motion_vectors.features) {
      data.motion_vectors.features.forEach((feat) => {
        const props = feat.properties;
        L.geoJSON(feat, {
          style: {
            color: "rgba(201, 168, 124, 0.85)",
            weight: 1.8,
          },
        }).addTo(layerMotionVectors);
      });
    }
  }

  // --------------------------------------------------------------------------
  // Scan Loading & Telemetry Updates
  // --------------------------------------------------------------------------
  async function loadScan(stampIndex) {
    if (!state.scans.length) return;
    state.currentScanIndex = Math.max(0, Math.min(stampIndex, state.scans.length - 1));
    const scanItem = state.scans[state.currentScanIndex];
    state.currentStamp = scanItem.stamp;

    // Update Scrubber UI
    dom.timelineScrubber.value = state.currentScanIndex;
    dom.sliderStampDisplay.textContent = scanItem.display_time;
    if (scanItem.is_forecast) {
      dom.sliderStepDesc.textContent = `แบบจำลองคาดการณ์ล่วงหน้า (+${scanItem.offset_min} นาที Nowcast Model)`;
      dom.sliderModeBadge.textContent = "NOWCAST FORECAST";
      dom.sliderModeBadge.style.color = "#D46A4C";
      dom.sliderModeBadge.style.borderColor = "rgba(212, 106, 76, 0.4)";
    } else {
      dom.sliderStepDesc.textContent = "สแกนจริงจากดาวเทียม Himawari-9 AHI Band 13";
      dom.sliderModeBadge.textContent = "REALTIME SCAN";
      dom.sliderModeBadge.style.color = "#C9A87C";
      dom.sliderModeBadge.style.borderColor = "rgba(201, 168, 124, 0.4)";
    }

    try {
      const res = await fetch(`/api/scans/${scanItem.stamp}`);
      if (!res.ok) throw new Error("Failed to load scan");
      const data = await res.json();
      state.scanData = data;

      // Update Zone A Telemetry
      const tel = data.telemetry || {};
      dom.telScanTime.textContent = `${data.utc_time} (${data.thai_time})`;
      dom.telLatency.textContent = `${tel.pipeline_latency_s || "3.37"}s`;
      dom.telActiveCells.textContent = data.summary.total_objects;
      dom.telWarnings.textContent = data.summary.onset_warnings;

      // Render Map
      renderMapLayers(data);

      // If Reticle target locked, refresh point analysis
      if (state.selectedPoint) {
        fetchPointNowcast(state.selectedPoint.lat, state.selectedPoint.lon);
      }
    } catch (err) {
      console.error("[ScanLoader] Error loading scan:", err);
    }
  }

  // --------------------------------------------------------------------------
  // Timeline Animation & Player Controls (Zone D)
  // --------------------------------------------------------------------------
  function togglePlay() {
    if (state.isPlaying) {
      stopPlayback();
    } else {
      startPlayback();
    }
  }

  function startPlayback() {
    state.isPlaying = true;
    dom.btnTimelinePlay.textContent = "❚❚";
    dom.btnTimelinePlay.style.background = "#FF2A5F";
    dom.btnTimelinePlay.style.color = "#FFFFFF";

    state.playIntervalId = setInterval(() => {
      let nextIdx = state.currentScanIndex + 1;
      if (nextIdx >= state.scans.length) {
        nextIdx = 0; // loop back
      }
      loadScan(nextIdx);
    }, state.playSpeedMs);
  }

  function stopPlayback() {
    state.isPlaying = false;
    dom.btnTimelinePlay.textContent = "▶";
    dom.btnTimelinePlay.style.background = "";
    dom.btnTimelinePlay.style.color = "";
    if (state.playIntervalId) {
      clearInterval(state.playIntervalId);
      state.playIntervalId = null;
    }
  }

  // --------------------------------------------------------------------------
  // SpaceX Mission Control Modal (Scenario 3)
  // --------------------------------------------------------------------------
  async function openMissionControlModal() {
    dom.missionControlModal.classList.remove("hidden");
    try {
      const stampParam = state.currentStamp ? `?stamp=${state.currentStamp}` : "";
      const res = await fetch(`/api/telemetry${stampParam}`);
      if (!res.ok) throw new Error("Telemetry fetch failed");
      const tel = await res.json();

      dom.modalTotalLatency.textContent = `${tel.pipeline_latency_s}s (${tel.pipeline_latency_ms} ms)`;
      dom.modalActiveTracks.textContent = `${tel.active_cells} Cells`;
      dom.modalOnsetWarnings.textContent = `${tel.onset_warnings} Warnings`;
      dom.modalBoundaryStatus.textContent = tel.boundary_flag ? `Warning (${tel.boundary_count} Cells Near Boundary)` : "Normal (Inside Domain)";
      dom.modalBoundaryStatus.className = tel.boundary_flag ? "sum-val font-mono text-amber" : "sum-val font-mono text-emerald";

      // Render Stage 1-6 breakdown bars
      dom.stagesBarsContainer.innerHTML = "";
      (tel.stages || []).forEach((stg) => {
        const row = document.createElement("div");
        row.className = "stage-row";
        row.innerHTML = `
          <div class="stage-meta">
            <span class="stage-name"><strong>${stg.stage}:</strong> ${stg.name}</span>
            <span class="stage-time">${stg.ms} ms (${stg.pct}%)</span>
          </div>
          <div class="stage-bar-bg">
            <div class="stage-bar-fill" style="width: ${Math.min(100, stg.pct * 1.5)}%;"></div>
          </div>
        `;
        dom.stagesBarsContainer.appendChild(row);
      });

      // Render Boundary Warning Log Terminal
      dom.boundaryLogTerminal.innerHTML = "";
      if (tel.boundary_logs && tel.boundary_logs.length) {
        tel.boundary_logs.forEach((log) => {
          const l = document.createElement("div");
          l.className = "log-line text-amber";
          l.textContent = `[BUFFER WARN] ${log}`;
          dom.boundaryLogTerminal.appendChild(l);
        });
      } else {
        dom.boundaryLogTerminal.innerHTML = `
          <div class="log-line text-emerald">[PIPELINE] All active convective cells remain within optimal processing boundary buffer.</div>
        `;
      }
    } catch (err) {
      console.error("[Modal] Error:", err);
    }
  }

  function closeMissionControlModal() {
    dom.missionControlModal.classList.add("hidden");
  }

  // --------------------------------------------------------------------------
  // Event Listeners & Binding
  // --------------------------------------------------------------------------
  function setupEventListeners() {
    // Zone A Telemetry Bar Click -> Mission Control Modal
    dom.telemetryBar.addEventListener("click", openMissionControlModal);
    dom.btnCloseModal.addEventListener("click", closeMissionControlModal);
    dom.missionControlModal.addEventListener("click", (e) => {
      if (e.target === dom.missionControlModal) closeMissionControlModal();
    });

    // View Mode Toggle
    dom.btnToggleViewMode.addEventListener("click", (e) => {
      e.stopPropagation();
      state.viewMode = state.viewMode === "operational" ? "physics" : "operational";
      dom.lblViewMode.textContent = state.viewMode === "operational" ? "Operational View" : "Physics / Research View";
      dom.btnToggleViewMode.style.borderColor = state.viewMode === "physics" ? "var(--cyan-telemetry)" : "";
      if (state.selectedPoint) fetchPointNowcast(state.selectedPoint.lat, state.selectedPoint.lon);
    });

    // Search input
    dom.btnSearchCoords.addEventListener("click", () => {
      const val = dom.coordSearchInput.value.trim();
      const parts = val.split(",").map((s) => parseFloat(s.trim()));
      if (parts.length === 2 && !isNaN(parts[0]) && !isNaN(parts[1])) {
        map.setView([parts[0], parts[1]], 9);
        lockTargetReticle(parts[0], parts[1]);
      } else {
        alert("กรุณาป้อนพิกัด ละติจูด, ลองจิจูด เช่น 13.7563, 100.5018");
      }
    });

    dom.coordSearchInput.addEventListener("keydown", (e) => {
      if (e.key === "Enter") dom.btnSearchCoords.click();
    });

    // GPS Button
    dom.btnMyGps.addEventListener("click", () => {
      if (navigator.geolocation) {
        navigator.geolocation.getCurrentPosition(
          (pos) => {
            const lat = parseFloat(pos.coords.latitude.toFixed(4));
            const lon = parseFloat(pos.coords.longitude.toFixed(4));
            map.setView([lat, lon], 10);
            lockTargetReticle(lat, lon);
          },
          (err) => {
            alert("ไม่สามารถดึงตำแหน่ง GPS ได้: " + err.message);
          }
        );
      } else {
        alert("เบราว์เซอร์ไม่รองรับ GPS Geolocation");
      }
    });

    // Preset Location Chips
    dom.presetChips.forEach((chip) => {
      chip.addEventListener("click", () => {
        const lat = parseFloat(chip.dataset.lat);
        const lon = parseFloat(chip.dataset.lon);
        map.setView([lat, lon], 9);
        lockTargetReticle(lat, lon);
      });
    });

    // Zone E Layer Toggles
    dom.btnLayerFootprints.addEventListener("click", () => {
      state.layers.footprints = !state.layers.footprints;
      dom.btnLayerFootprints.classList.toggle("active", state.layers.footprints);
      renderMapLayers(state.scanData);
    });

    dom.btnLayerParallax.addEventListener("click", () => {
      state.layers.parallax = !state.layers.parallax;
      dom.btnLayerParallax.classList.toggle("active", state.layers.parallax);
      renderMapLayers(state.scanData);
    });

    dom.btnLayerMotion.addEventListener("click", () => {
      state.layers.motion = !state.layers.motion;
      dom.btnLayerMotion.classList.toggle("active", state.layers.motion);
      renderMapLayers(state.scanData);
    });

    dom.btnFilterWarning.addEventListener("click", () => {
      state.layers.warningOnly = !state.layers.warningOnly;
      dom.btnFilterWarning.classList.toggle("active", state.layers.warningOnly);
      renderMapLayers(state.scanData);
    });

    dom.btnCompareParallax.addEventListener("click", () => {
      state.layers.compareParallax = !state.layers.compareParallax;
      state.layers.rawSatellite = state.layers.compareParallax;
      dom.btnCompareParallax.classList.toggle("active", state.layers.compareParallax);
      renderMapLayers(state.scanData);
    });

    // Zone C Inspector Drawer Close
    dom.btnCloseInspector.addEventListener("click", () => {
      dom.inspectorDrawer.classList.remove("open");
    });

    // Export CSV
    dom.btnExportCsv.addEventListener("click", () => {
      if (state.selectedTrackId) {
        window.open(`/api/objects/${state.selectedTrackId}/export`, "_blank");
      } else {
        alert("กรุณาเลือกเป้าหมายหรือก้อนเมฆก่อนดาวน์โหลด CSV");
      }
    });

    // Track Life-Log
    dom.btnTrackLog.addEventListener("click", () => {
      if (state.selectedTrackId) {
        alert(`Track ID: ${state.selectedTrackId}\nสถานะ: ติดตามต่อเนื่องในฐานข้อมูล (Stateful Tracking Engine)\nสามารถตรวจสอบประวัติทั้งหมดได้ใน Timeseries`);
      }
    });

    // Zone D Timeline Scrubber
    dom.timelineScrubber.addEventListener("input", (e) => {
      stopPlayback();
      loadScan(parseInt(e.target.value, 10));
    });

    dom.btnTimelinePlay.addEventListener("click", togglePlay);

    dom.btnTimelinePrev.addEventListener("click", () => {
      stopPlayback();
      loadScan(state.currentScanIndex - 1);
    });

    dom.btnTimelineNext.addEventListener("click", () => {
      stopPlayback();
      loadScan(state.currentScanIndex + 1);
    });

    // Speed controls
    dom.speedButtons.forEach((btn) => {
      btn.addEventListener("click", () => {
        dom.speedButtons.forEach((b) => b.classList.remove("active"));
        btn.classList.add("active");
        const spd = parseInt(btn.dataset.speed, 10);
        state.playSpeedMs = spd === 5 ? 400 : spd === 2 ? 900 : 1800;
        if (state.isPlaying) {
          stopPlayback();
          startPlayback();
        }
      });
    });
  }

  // --------------------------------------------------------------------------
  // Application Bootstrap
  // --------------------------------------------------------------------------
  async function init() {
    initMap();
    setupEventListeners();

    try {
      const res = await fetch("/api/scans");
      if (!res.ok) throw new Error("Could not fetch scans");
      const data = await res.json();
      state.scans = data.scans || [];

      if (state.scans.length) {
        dom.timelineScrubber.max = state.scans.length - 1;

        // Find latest observed scan (before forecast steps)
        let defaultIdx = state.scans.findIndex((s) => s.is_forecast);
        if (defaultIdx === -1) defaultIdx = state.scans.length - 1;
        else defaultIdx = Math.max(0, defaultIdx - 1);

        dom.lblNowMarker.textContent = `NOW [${state.scans[defaultIdx].utc_time}]`;
        await loadScan(defaultIdx);

        // Initial default lock on Bangkok
        lockTargetReticle(13.7563, 100.5018);

        // Setup real-time background sync polling every 30s
        setInterval(async () => {
          try {
            const res = await fetch("/api/scans");
            if (!res.ok) return;
            const data = await res.json();
            const newScans = data.scans || [];
            if (newScans.length > state.scans.length) {
              console.log(`[Realtime Sync] New scan detected! Total: ${newScans.length}`);
              const wasAtLatest = state.currentScanIndex >= state.scans.length - 1;
              state.scans = newScans;
              dom.timelineScrubber.max = state.scans.length - 1;
              let defaultIdx = state.scans.findIndex((s) => s.is_forecast);
              if (defaultIdx === -1) defaultIdx = state.scans.length - 1;
              else defaultIdx = Math.max(0, defaultIdx - 1);
              dom.lblNowMarker.textContent = `NOW [${state.scans[defaultIdx].utc_time}]`;
              if (wasAtLatest) {
                await loadScan(defaultIdx);
              }
            }
          } catch (e) {
            // quiet
          }
        }, 30000);

        setTimeout(() => {
          if (map) map.invalidateSize();
        }, 300);
      }
    } catch (err) {
      console.error("[Init] Error:", err);
    }
  }

  // Run on DOM ready
  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
