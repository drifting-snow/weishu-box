/* global pywebview */
(function () {
  const $ = (id) => document.getElementById(id);
  const STAGE_ORDER = ["early", "mid", "late"];
  const STAGE_LABEL = { early: "过渡 early", mid: "中期 mid", late: "大成 late" };
  // 卫戍协议：游戏板位恒为 8；kernel stages.pop 的 4-5/6-7 是「计划上场」曲线，不是人口上限
  const BOARD_CAP = 8;
  const RANK_ROMAN = { 1: "I", 2: "II", 3: "III", 4: "IV", 5: "V", 6: "VI" };

  let lastBoard = [];
  let lastComps = [];
  let selected = { id: null, stage: "mid" };

  function shopRank(u) {
    const t = u && (u.shop_tier != null ? u.shop_tier : u.tier);
    if (t == null || t === "") return null;
    const n = Number(t);
    if (!Number.isFinite(n)) return null;
    return RANK_ROMAN[n] || String(n);
  }

  function rankBadgeHtml(u) {
    const r = shopRank(u);
    if (!r) return '<span class="rank missing">等阶?</span>';
    return '<span class="rank">等阶 ' + escapeHtml(r) + "</span>";
  }

  function setStatus(text, kind) {
    const el = $("status");
    el.textContent = text || "";
    el.className = "status" + (kind ? " " + kind : "");
  }

  function escapeHtml(s) {
    return String(s)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  function ownedSet(board) {
    const s = new Set();
    (board || []).forEach((u) => {
      if (u && u.name) s.add(String(u.name));
    });
    return s;
  }

  function stageNames(comp, stageKey) {
    const st = (comp.stages || {})[stageKey] || {};
    return (st.units || []).map((u) => u && u.name).filter(Boolean);
  }

  function bondCountsHtml(comp, stageKey) {
    const st = (comp.stages || {})[stageKey] || {};
    let progress = st.bond_progress || null;
    let counts = st.bond_counts || null;
    if (!progress && !counts && stageKey !== "late") {
      const late = (comp.stages || {}).late || {};
      progress = late.bond_progress || null;
      counts = late.bond_counts || null;
    }
    const thresholds = comp.bond_thresholds || {};
    const cores = new Set(comp.core_bonds || []);
    const splash = new Set(comp.splash_bonds || []);
    const off = new Set(comp.off_board_bonds || []);

    const entries = [];
    if (progress && typeof progress === "object") {
      Object.keys(progress).forEach((k) => {
        const p = progress[k] || {};
        const rawN = p.n != null ? Number(p.n) : 0;
        const max = p.max != null ? Number(p.max) : rawN;
        entries.push({
          name: k,
          n: max > 0 ? Math.min(rawN, max) : rawN,
          max: max,
          off: !!p.off_board || off.has(k),
        });
      });
    } else if (counts && typeof counts === "object") {
      Object.keys(counts).forEach((k) => {
        const th = thresholds[k] || {};
        const max = Number(
          th.display_max != null
            ? th.display_max
            : (th.distinct_tiers || []).slice(-1)[0] ||
              th.activation_need ||
              counts[k]
        );
        const rawN = Number(counts[k]) || 0;
        entries.push({
          name: k,
          n: max > 0 ? Math.min(rawN, max) : rawN,
          max: max,
          off: !!th.off_board || off.has(k),
        });
      });
    }
    if (!entries.length) return "";

    entries.sort((a, b) => {
      const ra = cores.has(a.name) ? 0 : splash.has(a.name) ? 1 : 2;
      const rb = cores.has(b.name) ? 0 : splash.has(b.name) ? 1 : 2;
      if (ra !== rb) return ra - rb;
      return b.n - a.n;
    });

    return entries
      .filter((e) => e.n > 0)
      .slice(0, 8)
      .map((e) => {
        const hit =
          e.max && e.n >= e.max ? " hit" : e.max && e.n >= e.max / 2 ? " mid" : "";
        const cls =
          "bond-count" +
          (cores.has(e.name) ? " core" : splash.has(e.name) ? " splash" : "") +
          (e.off ? " offboard" : "") +
          hit;
        const label = e.max != null ? e.n + "/" + e.max : String(e.n);
        return (
          '<span class="' +
          cls +
          '" title="' +
          escapeHtml(e.name + " " + label + (e.off ? " · 整备区可激活" : "")) +
          '">' +
          escapeHtml(e.name) +
          "<b>" +
          escapeHtml(label) +
          "</b></span>"
        );
      })
      .join("");
  }

  function uniquePlanNames(comp, { boardOnly } = {}) {
    const seen = new Set();
    const names = [];
    STAGE_ORDER.forEach((k) => {
      const units = ((comp.stages || {})[k] || {}).units || [];
      units.forEach((u) => {
        if (!u || !u.name || seen.has(u.name)) return;
        if (boardOnly && String(u.role || "").toLowerCase() === "econ") return;
        seen.add(u.name);
        names.push(u.name);
      });
    });
    return names;
  }

  function allPlanNames(comp) {
    return uniquePlanNames(comp, { boardOnly: false });
  }

  function chaseFor(comp, stageKey) {
    const sk = stageKey || comp.current_stage || "early";
    const by = (comp.stage_chase || {})[sk];
    if (by) {
      return {
        next_targets: listNames(by.next_targets),
        off_board_targets: listNames(by.off_board_targets),
      };
    }
    // Fallback when sidecar did not attach stage_chase: split stage units by role.
    const owned = ownedSet(lastBoard);
    const next = [];
    const off = [];
    (((comp.stages || {})[sk] || {}).units || []).forEach((u) => {
      if (!u || !u.name || owned.has(u.name)) return;
      if (String(u.role || "").toLowerCase() === "econ") off.push(u.name);
      else next.push(u.name);
    });
    return {
      next_targets: next.slice(0, 4),
      off_board_targets: off.slice(0, 4),
    };
  }

  function listNames(arr) {
    if (!arr) return [];
    return arr
      .map((x) => (typeof x === "string" ? x : x && x.name))
      .filter(Boolean);
  }

  function ownershipHtml(comp) {
    const o = comp.ownership || {};
    if (o.owned == null && o.planned == null) return "";
    return (
      '<div class="own-meta" title="跨 early/mid/late 去重后的唯一干员数">持有 ' +
      escapeHtml(String(o.owned != null ? o.owned : "?")) +
      "/" +
      escapeHtml(String(o.planned != null ? o.planned : "?")) +
      "（唯一）</div>"
    );
  }

  function chaseStripsHtml(comp, stageKey) {
    const chase = chaseFor(comp, stageKey);
    const next = chase.next_targets || [];
    const off = chase.off_board_targets || [];
    const nextHtml = next.length
      ? '<div class="chase-strip board" title="上场追板 · 商店高亮来源"><span class="tag">追板</span> ' +
        next.map(escapeHtml).join(" · ") +
        "</div>"
      : '<div class="chase-strip board muted"><span class="tag">追板</span> 本阶段暂无</div>';
    const offHtml = off.length
      ? '<div class="chase-strip offboard" title="场下经济 · 不上商店追板高亮"><span class="tag">场下经济</span> ' +
        off.map(escapeHtml).join(" · ") +
        "</div>"
      : "";
    return nextHtml + offHtml;
  }

  function renderRoster(board, planNames) {
    const el = $("roster");
    const count = $("roster-count");
    const list = board || [];
    count.textContent = list.length ? "(" + list.length + ")" : "";
    if (!list.length) {
      el.className = "chip-row empty";
      el.textContent = "未识别到手牌干员（可检查准备界面手牌条）";
      return;
    }
    el.className = "chip-row";
    el.innerHTML = "";
    const plan = new Set(planNames || []);
    list.forEach((u) => {
      const chip = document.createElement("div");
      chip.className = "chip" + (plan.has(u.name) ? " on-plan" : "");
      const sub = [];
      const r = shopRank(u);
      if (r) sub.push("等阶 " + r);
      if (u.count && u.count > 1) sub.push("×" + u.count);
      if (u.elite) sub.push("精锐");
      if ((u.bonds || [])[0]) sub.push(u.bonds[0]);
      chip.innerHTML =
        escapeHtml(u.name || "?") +
        (sub.length ? '<span class="sub">' + escapeHtml(sub.join(" · ")) + "</span>" : "");
      el.appendChild(chip);
    });
  }

  function stageUnitsHtml(stage, owned, highlightNames, offBoardNames) {
    if (!stage || !Array.isArray(stage.units) || !stage.units.length) {
      return '<div class="muted">无单位</div>';
    }
    const hi = new Set(highlightNames || []);
    const off = new Set(offBoardNames || []);
    const cards = stage.units
      .map((u) => {
        const role = String(u.role || "support").toLowerCase();
        const isEcon = role === "econ";
        const ownedCls = owned.has(u.name) ? " owned" : "";
        // Glow only on-board chase — never 场下 econ even if listed in stage.
        const hiCls = !isEcon && hi.has(u.name) ? " glow" : "";
        const offCls = isEcon || off.has(u.name) ? " offboard-unit" : "";
        const roleCls =
          role === "carry" || role === "tank" || role === "heal" || role === "econ"
            ? " " + role
            : "";
        const note = u.note ? '<div class="note">' + escapeHtml(u.note) + "</div>" : "";
        const roleLabel = isEcon
          ? "econ · 场下"
          : escapeHtml(u.role || "support") + (owned.has(u.name) ? " · 有" : " · 缺");
        return (
          '<div class="unit-card' +
          roleCls +
          ownedCls +
          hiCls +
          offCls +
          '"><div class="name">' +
          escapeHtml(u.name) +
          "</div>" +
          rankBadgeHtml(u) +
          '<div class="role">' +
          roleLabel +
          "</div>" +
          note +
          "</div>"
        );
      })
      .join("");
    return '<div class="unit-grid">' + cards + "</div>";
  }

  async function applySelection(comp, stageKey) {
    selected = { id: comp.id, stage: stageKey };
    const chase = chaseFor(comp, stageKey);
    // Shop board glow = next_targets only (never mix off_board_targets).
    const glowNames = chase.next_targets || [];
    renderRoster(lastBoard, uniquePlanNames(comp, { boardOnly: true }));
    markCompUi();
    if (!window.pywebview || !window.pywebview.api) return;
    const res = await window.pywebview.api.select_lineup_highlight(
      comp.id,
      stageKey,
      glowNames
    );
    const glow = res && res.glow_count != null ? res.glow_count : "?";
    const offN = (chase.off_board_targets || []).length;
    setStatus(
      "已选 " +
        (comp.name || comp.id) +
        " · " +
        STAGE_LABEL[stageKey] +
        " · 追板高亮 " +
        glow +
        " 张" +
        (offN ? " · 场下经济 " + offN + "（不高亮）" : ""),
      "ok"
    );
  }

  function markCompUi() {
    document.querySelectorAll(".comp").forEach((el) => {
      const id = el.getAttribute("data-id");
      el.classList.toggle("selected", id === selected.id);
      el.querySelectorAll(".stage-tab").forEach((tab) => {
        const st = tab.getAttribute("data-stage");
        tab.classList.toggle("active", id === selected.id && st === selected.stage);
      });
      el.querySelectorAll(".stage-panel").forEach((panel) => {
        const st = panel.getAttribute("data-stage");
        const open = id === selected.id && st === selected.stage;
        panel.hidden = !open;
      });
    });
  }

  function renderComps(comps, board) {
    const el = $("comps");
    const list = comps || [];
    if (!list.length) {
      el.className = "comps empty";
      el.textContent = "暂无推荐 · 先「录入本局」+「OCR 识别」";
      return;
    }
    el.className = "comps";
    el.innerHTML = "";
    const owned = ownedSet(board);

    list.forEach((c, idx) => {
      const wrap = document.createElement("div");
      wrap.className =
        "comp" +
        (c.inferred ? " inferred" : "") +
        (idx === 0 ? " top" : "") +
        (selected.id === c.id ? " selected" : "");
      wrap.setAttribute("data-id", c.id || "");

      const badge = c.inferred
        ? "罗盘推断"
        : c.archetype_label || c.archetype || "";
      const fantasy = c.fantasy || c.counter_why || c.why || "";
      const fit = c.fit_score != null ? "契合 " + c.fit_score : "";
      const hits = (c.counter_hits || []).length
        ? "克制 " + (c.counter_hits || []).join("/")
        : "";
      // Card header: late (满编) bond counts e.g. 奥术6 卡西米尔6
      const headerCounts = bondCountsHtml(c, "late");

      const tabs = STAGE_ORDER.map((k) => {
        const st = (c.stages || {})[k];
        if (!st || !(st.units || []).length) return "";
        const n = (st.units || []).length;
        const active =
          selected.id === c.id && selected.stage === k ? " active" : "";
        return (
          '<button type="button" class="stage-tab' +
          active +
          '" data-stage="' +
          k +
          '">' +
          STAGE_LABEL[k] +
          " · " +
          n +
          "</button>"
        );
      }).join("");

      const panels = STAGE_ORDER.map((k) => {
        const st = (c.stages || {})[k];
        if (!st || !(st.units || []).length) return "";
        const open = selected.id === c.id && selected.stage === k;
        const goal = st.goal || "";
        const planN = (st.units || []).length;
        const desc =
          "板位 " +
          BOARD_CAP +
          " · 本阶段计划 " +
          planN +
          " 人" +
          (goal ? " · " + goal : "");
        const stageBonds = bondCountsHtml(c, k);
        const chase = chaseFor(c, k);
        return (
          '<div class="stage-panel" data-stage="' +
          k +
          '"' +
          (open ? "" : " hidden") +
          ">" +
          '<div class="stage-desc">' +
          escapeHtml(desc) +
          "</div>" +
          chaseStripsHtml(c, k) +
          (stageBonds
            ? '<div class="bond-counts">' + stageBonds + "</div>"
            : "") +
          stageUnitsHtml(
            st,
            owned,
            open ? chase.next_targets : [],
            chase.off_board_targets
          ) +
          "</div>"
        );
      }).join("");

      const defaultStage =
        c.current_stage &&
        (c.stages || {})[c.current_stage] &&
        (((c.stages || {})[c.current_stage] || {}).units || []).length
          ? c.current_stage
          : "early";
      const headerChase = chaseStripsHtml(
        c,
        selected.id === c.id ? selected.stage : defaultStage
      );

      wrap.innerHTML =
        '<button type="button" class="comp-head select-lineup">' +
        '<div class="comp-name">' +
        (idx === 0 ? "★ " : "") +
        escapeHtml(c.name || c.id || "阵容") +
        '</div><div class="comp-meta">' +
        escapeHtml(badge) +
        (c.current_stage
          ? " · " + (STAGE_LABEL[c.current_stage] || c.current_stage)
          : "") +
        "</div></button>" +
        ownershipHtml(c) +
        (headerCounts
          ? '<div class="bond-counts header">' + headerCounts + "</div>"
          : "") +
        '<div class="comp-stats">' +
        [fit, hits].filter(Boolean).map(escapeHtml).join(" · ") +
        "</div>" +
        headerChase +
        (fantasy
          ? '<div class="fantasy">' + escapeHtml(fantasy) + "</div>"
          : "") +
        ((c.reserve_plan || []).length
          ? '<div class="reserve">整备区：' +
            (c.reserve_plan || [])
              .map((u) => escapeHtml((u && u.name) || ""))
              .filter(Boolean)
              .join(" · ") +
            "</div>"
          : "") +
        '<div class="stage-tabs">' +
        tabs +
        "</div>" +
        panels;

      // Click header → expand current_stage (dispatch-mapped), not hard mid/8.
      wrap.querySelector(".select-lineup").addEventListener("click", () => {
        let stage = defaultStage;
        if (!(c.stages || {})[stage] || !(((c.stages || {})[stage] || {}).units || []).length) {
          stage = STAGE_ORDER.find(
            (k) => (c.stages || {})[k] && ((c.stages[k] || {}).units || []).length
          ) || "late";
        }
        applySelection(c, stage);
      });

      wrap.querySelectorAll(".stage-tab").forEach((tab) => {
        tab.addEventListener("click", (ev) => {
          ev.stopPropagation();
          applySelection(c, tab.getAttribute("data-stage") || "mid");
        });
      });

      el.appendChild(wrap);
    });
  }

  function renderPayload(payload) {
    const data = payload && payload.result ? payload.result : payload || {};
    lastBoard =
      data.board ||
      (data.state && data.state.board) ||
      [];
    lastComps = data.target_comps || [];
    // Keep selection if still present
    if (selected.id && !lastComps.some((c) => c.id === selected.id)) {
      selected = { id: null, stage: "mid" };
    }
    const focus =
      (selected.id && lastComps.find((c) => c.id === selected.id)) ||
      lastComps[0] ||
      {};
    renderRoster(lastBoard, uniquePlanNames(focus, { boardOnly: true }));
    renderComps(lastComps, lastBoard);
    if (data.enemy_panel) {
      renderEnemyWave(data.enemy_panel);
    } else if (data.state && (data.state.enemy_types || []).length) {
      renderEnemyWave({
        names: data.state.enemy_types,
        trait_keys: data.state.enemy_types,
      });
    }
    const top = lastComps[0];
    const enemies =
      (data.state && data.state.enemy_types) ||
      (top && top.enemy_sort) ||
      [];
    const enemyHint = enemies.length
      ? " · 克制序 " + enemies.join("/")
      : "";
    const own = top && top.ownership;
    const ownHint =
      own && own.planned != null
        ? " · 唯一 " + (own.owned || 0) + "/" + own.planned
        : "";
    const chaseHint =
      top && (top.next_targets || []).length
        ? " · 追板 " + (top.next_targets || []).slice(0, 3).join("/")
        : "";
    setStatus(
      "阵容 " +
        lastBoard.length +
        " · 推荐 " +
        lastComps.length +
        (top ? " · 首选 " + (top.name || top.id) : "") +
        ownHint +
        chaseHint +
        enemyHint +
        (selected.id ? " · 已选 " + selected.stage : " · 点阵容展开过渡") +
        (payload && payload.latency_ms != null ? " · " + payload.latency_ms + "ms" : ""),
      "ok"
    );
  }

  window.__weishu_roster_render = renderPayload;

  function renderEnemyWave(panelOrEnv) {
    const el = $("enemy-wave");
    if (!el) return;
    const panel = panelOrEnv || {};
    const names =
      panel.names ||
      panel.enemy_wave_names ||
      [];
    const keys = panel.trait_keys || panel.enemy_types || [];
    const resolutions = panel.resolutions || panel.enemy_wave_resolutions || [];
    if (!names.length) {
      el.className = "enemy-wave muted";
      el.textContent =
        "本波敌人：主面板「读敌人」会自动按 W 开放大镜再 OCR";
      return;
    }
    el.className = "enemy-wave";
    const detail = resolutions.length
      ? resolutions
          .map((r) => {
            const nm = (r && (r.name || r.input)) || "?";
            const st = (r && r.status) || "";
            if (st === "tactical") {
              const tk = ((r.trait_keys || []).join("/")) || "?";
              return nm + "(" + tk + ")";
            }
            if (st === "untyped") return nm + "(普通)";
            return nm;
          })
          .join(" · ")
      : names.join(" · ");
    const keyHint = keys.length ? " · 克制词条 " + keys.join("/") : "";
    el.innerHTML =
      '<span class="tag">本波敌人</span>' +
      escapeHtml(detail) +
      escapeHtml(keyHint);
  }

  function renderRunEnv(payload) {
    const list = $("run-env-list");
    const pathEl = $("run-env-path");
    if (!list) return;
    const summary = (payload && payload.summary) || [];
    if (pathEl) {
      const p = (payload && payload.path) || "";
      pathEl.textContent = p ? p.replace(/^.*[\\/](session[\\/].*)$/i, "$1") : "";
      pathEl.title = p || "";
    }
    list.innerHTML = "";
    if (!summary.length) {
      list.innerHTML = '<li class="muted">尚未录入 · 主面板点「录入本局」</li>';
    } else {
      summary.forEach((line) => {
        const li = document.createElement("li");
        li.textContent = line;
        list.appendChild(li);
      });
    }
    const env = (payload && payload.env) || {};
    const panel = (payload && payload.enemy_panel) || null;
    renderEnemyWave(panel || env);
  }

  window.__weishu_run_env_render = renderRunEnv;

  function setCollapsed(on) {
    document.body.classList.toggle("collapsed", !!on);
    const btn = $("btn-hide");
    if (btn) {
      btn.textContent = on ? "展" : "隐";
      btn.title = on ? "展开阵容窗" : "折叠内容（不关窗）";
    }
  }

  window.__roster_set_collapsed = setCollapsed;

  $("btn-hide").addEventListener("click", async () => {
    if (!window.pywebview || !window.pywebview.api) return;
    const collapsed = await window.pywebview.api.toggle_roster_collapsed();
    setCollapsed(!!collapsed);
  });

  (function bindChromeDrag() {
    const bar = $("drag-bar");
    if (!bar) return;
    bar.classList.add("pywebview-drag-region");
    let dragging = false;
    let ox = 0;
    let oy = 0;
    const moveTo = (x, y) => {
      if (window.pywebview && typeof window.pywebview._jsApiCallback === "function") {
        window.pywebview._jsApiCallback("pywebviewMoveWindow", [x, y], "move");
        return;
      }
      if (window.pywebview && window.pywebview.api && window.pywebview.api.drag_move) {
        window.pywebview.api.drag_move("roster", x, y);
      }
    };
    const onMove = (ev) => {
      if (!dragging) return;
      moveTo(ev.screenX - ox, ev.screenY - oy);
    };
    const onUp = () => {
      if (!dragging) return;
      dragging = false;
      window.removeEventListener("pointermove", onMove, true);
      window.removeEventListener("pointerup", onUp, true);
      window.removeEventListener("mousemove", onMove, true);
      window.removeEventListener("mouseup", onUp, true);
      if (window.pywebview && window.pywebview.api && window.pywebview.api.end_drag) {
        window.pywebview.api.end_drag("roster");
      }
    };
    bar.addEventListener("pointerdown", (ev) => {
      if (ev.button !== 0) return;
      const t = ev.target;
      if (t && t.closest && t.closest(".bar-actions, button, a, input, select, textarea, label")) {
        return;
      }
      if (!window.pywebview) return;
      ev.preventDefault();
      dragging = true;
      ox = ev.clientX;
      oy = ev.clientY;
      try { bar.setPointerCapture(ev.pointerId); } catch (_) {}
      if (window.pywebview.api && window.pywebview.api.start_drag) {
        window.pywebview.api.start_drag("roster");
      }
      window.addEventListener("pointermove", onMove, true);
      window.addEventListener("pointerup", onUp, true);
      window.addEventListener("mousemove", onMove, true);
      window.addEventListener("mouseup", onUp, true);
    });
  })();

  $("btn-clear-sel").addEventListener("click", async () => {
    selected = { id: null, stage: "early" };
    if (window.pywebview && window.pywebview.api) {
      await window.pywebview.api.clear_lineup_highlight();
    }
    renderRoster(lastBoard, uniquePlanNames(lastComps[0] || {}, { boardOnly: true }));
    markCompUi();
    setStatus("已清除阵容高亮", "ok");
  });

  window.addEventListener("pywebviewready", async () => {
    setStatus("就绪 · 点阵容展开 early/mid/late");
    try {
      const envRes = await window.pywebview.api.get_run_env();
      if (envRes && envRes.ok && envRes.env && envRes.env.captured_at) {
        renderRunEnv(envRes);
      }
      const lin = await window.pywebview.api.refresh_lineups({});
      if (lin && lin.ok) renderPayload(lin);
      const sel = await window.pywebview.api.get_lineup_selection();
      if (sel && sel.id) {
        selected = { id: sel.id, stage: sel.stage || "mid" };
        markCompUi();
      }
    } catch (e) {
      /* ignore */
    }
  });
})();
