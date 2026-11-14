/* global pywebview */
(function () {
  const $ = (id) => document.getElementById(id);
  const TOP_N = 3;
  const NOTES_N = 2;

  /* 12 卫戍 Moji — keys match docs/weishu-moji-12.md (#1–#12) */
  const MOJI = {
    happy: "assets/moji/01-happy.png",
    scared: "assets/moji/02-scared.png",
    sorry: "assets/moji/03-sorry.png",
    thanks: "assets/moji/04-thanks.png",
    thinking: "assets/moji/05-thinking.png",
    cooperate: "assets/moji/06-cooperate.png",
    noproblem: "assets/moji/07-noproblem.png",
    respect: "assets/moji/08-respect.png",
    call: "assets/moji/09-call.png",
    easy: "assets/moji/10-easy.png",
    sad: "assets/moji/11-sad.png",
    dying: "assets/moji/12-dying.png",
  };
  const MOJI_KEYS = Object.keys(MOJI);

  const Moji = (function createMoji() {
    let holdTimer = null;
    let swapTimer = null;
    let finishTimer = null;
    let idleFxTimer = null;
    let gen = 0;
    let ready = false;
    let anim = null;
    const badge = () => $("moji-badge");
    const face = () => $("moji-face");
    const xform = () => $("moji-xform");
    const fx = () => $("moji-fx");
    // Thinking loops until OCR returns — no fixed think duration.
    // Morph length is fixed (~900ms) and only starts on easy()/sorry().
    const MORPH_MS = 900;

    function clearHold() {
      if (holdTimer) {
        clearTimeout(holdTimer);
        holdTimer = null;
      }
    }

    function clearSwap() {
      if (swapTimer) {
        clearTimeout(swapTimer);
        swapTimer = null;
      }
      if (finishTimer) {
        clearTimeout(finishTimer);
        finishTimer = null;
      }
    }

    function clearIdleFx() {
      if (idleFxTimer) {
        clearInterval(idleFxTimer);
        idleFxTimer = null;
      }
    }

    function clearFx() {
      clearIdleFx();
      const layer = fx();
      if (layer) layer.innerHTML = "";
    }

    function cancelAnim() {
      clearSwap();
      clearFx();
      if (anim) {
        try {
          anim.cancel();
        } catch (_) {}
        anim = null;
      }
      const box = xform();
      if (box) {
        box.style.transform = "";
        try {
          box.getAnimations().forEach((a) => a.cancel());
        } catch (_) {}
      }
    }

    function preload() {
      const urls = MOJI_KEYS.map((k) => MOJI[k]);
      return Promise.all(
        urls.map(
          (src) =>
            new Promise((resolve) => {
              const img = new Image();
              img.onload = img.onerror = () => resolve(src);
              img.src = src;
            })
        )
      ).then(() => {
        ready = true;
        const img = face();
        if (img && !img.getAttribute("src")) img.src = MOJI.thinking;
      });
    }

    function setEmotion(el, key) {
      if (!el) return;
      el.dataset.emotion = key || "";
    }

    /**
     * Show any of the 12 Moji with its tailored idle loop (future UI states).
     * OCR path still uses thinking()/easy()/sorry() specifically.
     */
    function show(key, holdMs) {
      const k = MOJI[key] ? key : "happy";
      const my = ++gen;
      clearHold();
      cancelAnim();
      const el = badge();
      const img = face();
      const box = xform();
      if (!el || !img) return;
      img.src = MOJI[k];
      if (box) box.style.transform = "";
      setEmotion(el, k);
      el.dataset.state = "loop";
      if (holdMs != null && holdMs > 0) {
        holdTimer = setTimeout(() => {
          if (my !== gen) return;
          clearFx();
          el.dataset.state = "idle";
          setEmotion(el, "");
        }, holdMs);
      }
    }

    function spawnSpark(opts) {
      const layer = fx();
      if (!layer) return;
      const d = document.createElement("span");
      d.className = "moji-spark" + (opts.tall ? " tall" : "");
      if (opts.idle) d.classList.add("idle");
      layer.appendChild(d);
      const ang = opts.ang;
      const dist = opts.dist;
      const dx = Math.cos(ang) * dist;
      const dy = Math.sin(ang) * dist - (opts.idle ? 2 : 4);
      const life = opts.life;
      const peak = opts.idle ? 0.45 : 0.95;
      if (typeof d.animate === "function") {
        d.animate(
          [
            { transform: "translate(0,0) scale(0.35)", opacity: 0, offset: 0 },
            {
              transform: "translate(" + dx * 0.35 + "px," + dy * 0.25 + "px) scale(1)",
              opacity: peak,
              offset: 0.2,
            },
            {
              transform: "translate(" + dx + "px," + dy + "px) scale(0.5)",
              opacity: 0,
              offset: 1,
            },
          ],
          {
            duration: life,
            easing: "cubic-bezier(0.22, 0.8, 0.36, 1)",
            fill: "forwards",
          }
        ).finished
          .then(() => {
            if (d.parentNode) d.parentNode.removeChild(d);
          })
          .catch(() => {
            if (d.parentNode) d.parentNode.removeChild(d);
          });
      }
    }

    /** Success/fail morph burst — short cyan sparks. */
    function burstSparks() {
      const layer = fx();
      if (!layer) return;
      // Keep layer; remove prior idle crumbs only.
      layer.querySelectorAll(".moji-spark.idle").forEach((n) => n.remove());
      const n = 14;
      for (let i = 0; i < n; i++) {
        spawnSpark({
          ang: (Math.PI * 2 * i) / n + (Math.random() * 0.35 - 0.17),
          dist: 18 + Math.random() * 22,
          life: 420 + Math.random() * 220,
          tall: i % 3 === 0,
          idle: false,
        });
      }
    }

    /** Soft idle crumbs while OCR runs — keeps going until gen changes. */
    function startIdleSparks(myGen) {
      clearIdleFx();
      function tick() {
        if (myGen !== gen) {
          clearIdleFx();
          return;
        }
        const el = badge();
        if (!el || el.dataset.state !== "thinking") return;
        const count = 2 + Math.floor(Math.random() * 2);
        for (let i = 0; i < count; i++) {
          spawnSpark({
            ang: Math.random() * Math.PI * 2,
            dist: 10 + Math.random() * 14,
            life: 700 + Math.random() * 400,
            tall: Math.random() < 0.35,
            idle: true,
          });
        }
      }
      tick();
      idleFxTimer = setInterval(tick, 900);
    }

    /**
     * OCR start: #5 thinking loop until easy()/sorry()/idle().
     * No fixed think duration — CSS breathe + idle sparks keep going for 7s+ OCR.
     * New call cancels pending morph/hold and restarts the loop.
     */
    function thinking() {
      gen += 1;
      const myGen = gen;
      clearHold();
      cancelAnim();
      const el = badge();
      const img = face();
      const box = xform();
      if (!el || !img) return;
      img.src = MOJI.thinking;
      if (box) box.style.transform = "";
      setEmotion(el, "thinking");
      el.dataset.state = "thinking";
      startIdleSparks(myGen);
    }

    function finishHold(my, el, endState, holdMs) {
      if (my !== gen || !el) return;
      const box = xform();
      if (box) box.style.transform = "";
      // endState easy/sorry → matching emotion idle loop during hold
      setEmotion(el, endState === "easy" ? "easy" : endState === "sorry" ? "sorry" : endState);
      el.dataset.state = endState;
      anim = null;
      clearHold();
      holdTimer = setTimeout(() => {
        if (my !== gen) return;
        clearFx();
        el.dataset.state = "idle";
        setEmotion(el, "");
      }, holdMs == null ? 1400 : holdMs);
    }

    /**
     * OCR finished → morph (~MORPH_MS). Only call from easy()/sorry().
     * WAAPI on #moji-xform; img.src swap cannot cancel it.
     */
    function morphTo(src, endState, holdMs) {
      const my = ++gen;
      clearHold();
      cancelAnim();
      const el = badge();
      const img = face();
      const box = xform();
      if (!el || !img || !box) return;
      // Prefer staying on thinking face until swap — if already mid-frame, keep it.
      if (!img.getAttribute("src")) img.src = MOJI.thinking;
      el.dataset.state = "morphing";
      setEmotion(el, "");
      img.style.filter = "none";
      img.style.opacity = "1";
      img.style.mixBlendMode = "normal";
      box.style.transform = "";

      const duration = MORPH_MS;
      const swapAt = 0.4;
      let swapped = false;
      let finished = false;
      const hold = holdMs == null ? 1400 : holdMs;

      function swapOnce() {
        if (swapped) return;
        swapped = true;
        img.src = src;
        burstSparks();
      }

      function onMorphDone() {
        if (finished || my !== gen) return;
        finished = true;
        clearSwap();
        swapOnce();
        if (anim) {
          try {
            anim.cancel();
          } catch (_) {}
          anim = null;
        }
        finishHold(my, el, endState, hold);
      }

      const keyframes = [
        { transform: "scale(1, 1) rotate(0deg)", offset: 0 },
        { transform: "scale(1.04, 0.9) rotate(-1deg)", offset: 0.22 },
        { transform: "scale(1.06, 0.82) rotate(-1.2deg)", offset: 0.4 },
        { transform: "scale(0.94, 1.06) rotate(1deg)", offset: 0.62 },
        { transform: "scale(1.02, 0.99)", offset: 0.82 },
        { transform: "scale(1, 1) rotate(0deg)", offset: 1 },
      ];

      if (typeof box.animate === "function") {
        anim = box.animate(keyframes, {
          duration: duration,
          easing: "cubic-bezier(0.33, 0.12, 0.25, 1)",
          fill: "forwards",
          composite: "replace",
        });
        swapTimer = setTimeout(swapOnce, Math.round(duration * swapAt));
        finishTimer = setTimeout(onMorphDone, duration + 20);
        if (anim && anim.finished) {
          anim.finished
            .then(() => {
              if (my !== gen) return;
              onMorphDone();
            })
            .catch(() => {});
        }
      } else {
        box.style.transition = "transform 0.28s cubic-bezier(0.33, 0.12, 0.25, 1)";
        box.style.transform = "scale(1.05, 0.84)";
        swapTimer = setTimeout(() => {
          swapOnce();
          box.style.transform = "scale(0.95, 1.05)";
          finishTimer = setTimeout(() => {
            box.style.transform = "";
            box.style.transition = "";
            onMorphDone();
          }, 360);
        }, 320);
      }
    }

    /** OCR success — call only when result returns. */
    function easy(holdMs) {
      morphTo(MOJI.easy, "easy", holdMs == null ? 1400 : holdMs);
    }

    /** OCR fail — call only when result returns. */
    function sorry(holdMs) {
      morphTo(MOJI.sorry, "sorry", holdMs == null ? 1200 : holdMs);
    }

    function idle() {
      gen += 1;
      clearHold();
      cancelAnim();
      const el = badge();
      if (el) {
        el.dataset.state = "idle";
        setEmotion(el, "");
      }
    }

    return {
      preload,
      thinking,
      easy,
      sorry,
      idle,
      show,
      catalog: MOJI,
      keys: MOJI_KEYS,
      get ready() {
        return ready;
      },
    };
  })();

  window.__weishu_moji = Moji;
  Moji.preload();

  function setStatus(text, kind) {
    const el = $("status");
    el.textContent = text;
    el.className = "status" + (kind ? " " + kind : "");
  }

  function metaFromForm() {
    return {
      round: Number($("round").value) || 1,
      gold: Number($("gold").value) || 0,
      dispatch_level: Number($("dispatch").value) || 1,
      target_bond: ($("bond").value || "").trim(),
      difficulty: "standard",
    };
  }

  function verbColor(verb) {
    const v = (verb || "").toLowerCase();
    if (v === "buy") return "#5b9cff";
    if (v === "upgrade") return "#e8b84a";
    if (v === "refresh") return "#c084fc";
    if (v === "freeze") return "#67e8f9";
    if (v === "merge") return "#3ecf8e";
    if (v === "ready" || v === "battle" || v === "开战" || v === "准备就绪") return "#5dffb0";
    return "#9aa8bc";
  }

  function samePick(a, b) {
    if (!a || !b) return false;
    return (
      String(a.verb || "").toLowerCase() === String(b.verb || "").toLowerCase() &&
      String(a.target || "") === String(b.target || "")
    );
  }

  function renderOcrMeta(data) {
    const el = $("ocr-meta");
    const res = data.resources || null;
    if (!res) {
      el.innerHTML = "OCR 元数据：本次无 resources（手填 / Mock）";
      return;
    }
    function chip(label, val, key) {
      const ok = val != null && val !== "";
      const cls = ok ? "hit" : "miss";
      const shown = ok ? String(val) : "未识别→手填";
      return '<span class="' + cls + '">' + label + " " + shown + "</span>";
    }
    const gStatus = res.gold_status || "";
    let goldLabel = res.gold;
    if (gStatus === "last_good" && res.gold != null) {
      goldLabel = String(res.gold) + "(沿用)";
    } else if (gStatus === "unknown" || (res.gold == null && gStatus)) {
      goldLabel = null;
    }
    const warns = (res.warnings || [])
      .filter((w) => !String(w).includes("gold unrecognized"))
      .slice(0, 2)
      .join("；");
    el.innerHTML =
      "OCR：" +
      chip("回合", res.round, "round") +
      " · " +
      chip("金币", goldLabel, "gold") +
      (gStatus === "unknown" ? '<span class="miss"> · 金币未确认≠开战</span>' : "") +
      " · " +
      chip("调度", res.dispatch_level, "dispatch") +
      (warns ? " · " + warns : "") +
      "（可手改）";
  }

  function fillMetaFields(data) {
    // Prefer engine state (already merged OCR + fallbacks); then resources.
    const st = data.state || {};
    const res = data.resources || {};
    const round = st.round != null ? st.round : res.round;
    const gold = st.gold != null ? st.gold : res.gold;
    const level = st.dispatch_level != null ? st.dispatch_level : res.dispatch_level;
    if (round != null) $("round").value = round;
    // Only overwrite form gold when OCR/last_good confirmed — never write 0 from miss.
    const gStat = (data.resources && data.resources.gold_status) || "";
    if (gold != null && gStat !== "unknown") $("gold").value = gold;
    if (level != null) $("dispatch").value = level;
    if (st.target_bond) $("bond").value = st.target_bond;
  }

  function renderShopMirror(data, topPick) {
    const sec = $("shop-mirror-sec");
    const slots = $("shop-slots");
    slots.innerHTML = "";
    const shop = (data.state && data.state.shop) || data.shop || null;
    let cards = [];
    if (Array.isArray(shop) && shop.length) {
      cards = shop.map((c) => ({
        name: c.name || c.target || "?",
        kind: c.kind || "",
      }));
    } else {
      const seen = new Set();
      (data.recommendations || []).forEach((r) => {
        if ((r.verb || "").toLowerCase() !== "buy") return;
        const name = r.target || "";
        if (!name || seen.has(name)) return;
        seen.add(name);
        cards.push({ name: name, kind: "operator" });
      });
    }
    if (!cards.length) {
      sec.hidden = true;
      return;
    }
    sec.hidden = false;
    const glowName =
      topPick && (topPick.verb || "").toLowerCase() === "buy" ? topPick.target : null;
    cards.slice(0, 5).forEach((c) => {
      const el = document.createElement("div");
      el.className = "slot" + (glowName && c.name === glowName ? " slot-glow" : "");
      el.textContent = c.name;
      slots.appendChild(el);
    });
  }

  function renderResult(payload) {
    const data = payload && payload.result ? payload.result : payload;
    if (!data) return;

    fillMetaFields(data);
    renderOcrMeta(data);

    const tp = data.top_pick || null;
    const box = $("top-pick");
    if (!tp) {
      box.classList.add("empty");
      $("tp-verb").textContent = "—";
      $("tp-target").textContent = "无主建议";
      $("tp-score").textContent = "";
      $("tp-cost").textContent = "";
      $("tp-reason").textContent = "";
    } else {
      box.classList.remove("empty");
      const verbLabel =
        tp.label ||
        (String(tp.verb || "").toLowerCase() === "ready"
          ? "位置调节并开战"
          : (tp.verb || "").toUpperCase());
      $("tp-verb").textContent = verbLabel;
      $("tp-verb").style.color = verbColor(tp.verb);
      $("tp-target").textContent = tp.target || "—";
      $("tp-score").textContent = tp.score != null ? "score " + tp.score : "";
      $("tp-cost").textContent = tp.cost != null ? "花费 " + tp.cost : "";
      $("tp-reason").textContent = tp.reason || "";
    }

    const list = $("rec-list");
    list.innerHTML = "";
    const recs = (data.recommendations || []).slice(0, TOP_N);
    if (!recs.length) {
      list.innerHTML = "<li>无候选</li>";
    } else {
      recs.forEach((r, idx) => {
        if (r.shell_demoted || r.affordable === false) {
          // Hide unaffordable buys from the main candidate strip
          return;
        }
        const li = document.createElement("li");
        const glow = (tp && samePick(r, tp)) || (!tp && idx === 0);
        if (glow) li.classList.add("rec-glow");
        li.innerHTML =
          '<span class="verb" style="color:' +
          verbColor(r.verb) +
          '">' +
          (r.verb || "") +
          "</span> " +
          (r.target || "") +
          ' <span style="color:#9aa8bc">· ' +
          (r.score != null ? r.score : "") +
          "</span>";
        list.appendChild(li);
      });
      if (!list.children.length) {
        list.innerHTML = "<li>无候选</li>";
      }
    }

    renderShopMirror(data, tp);

    const bonds = $("bond-list");
    bonds.innerHTML = "";
    let bondArr = data.bond_status;
    if (bondArr && !Array.isArray(bondArr) && typeof bondArr === "object") {
      bondArr = Object.keys(bondArr).map((k) => {
        const v = bondArr[k] || {};
        return {
          bond: k,
          have: v.have ?? v.count ?? 0,
          need: v.need ?? v.threshold ?? 0,
          active: !!v.active,
        };
      });
    }
    bondArr = (bondArr || []).slice(0, 4);
    if (!bondArr.length) {
      bonds.innerHTML = '<div style="color:#9aa8bc">—</div>';
    } else {
      bondArr.forEach((b) => {
        const have = b.have || 0;
        const need = b.need || 1;
        const pct = Math.min(100, Math.round((have / need) * 100));
        const row = document.createElement("div");
        row.innerHTML =
          '<div class="bond-row"><span>' +
          (b.bond || "") +
          (b.active ? " ✓" : "") +
          "</span><span>" +
          have +
          "/" +
          need +
          '</span></div><div class="bar-track"><div class="bar-fill" style="width:' +
          pct +
          '%"></div></div>';
        bonds.appendChild(row);
      });
    }

    const notes = $("note-list");
    notes.innerHTML = "";
    (data.notes || []).slice(0, NOTES_N).forEach((n) => {
      const li = document.createElement("li");
      li.textContent = typeof n === "string" ? n : JSON.stringify(n);
      notes.appendChild(li);
    });

    const shop = (data.state && data.state.shop) || data.shop || null;
    const level =
      (data.state && data.state.dispatch_level) != null
        ? data.state.dispatch_level
        : data.resources && data.resources.dispatch_level != null
          ? data.resources.dispatch_level
          : Number($("dispatch").value) || 1;
    // Re-anchor glow after panel paint using Python-side last OCR shop
    // (keeps raw.cx_frac). Do NOT re-resolve from JS shop — that dropped raw
    // and left-padded slot index, looking like drift across OCR cycles.
    if (tp) {
      return call("reassert_last_highlight");
    }
    return call("clear_highlight");
  }

  async function call(method, ...args) {
    if (!window.pywebview || !window.pywebview.api) {
      setStatus("API 未就绪", "err");
      return null;
    }
    return window.pywebview.api[method](...args);
  }

  async function runOcrLikeMock(meta) {
    const m = meta || metaFromForm();
    Moji.thinking();
    setStatus("OCR 识别中：已清除旧绿框，抓主屏…");
    // Clear glow immediately (also done server-side at analyze start).
    await call("clear_highlight");
    const res = await call("analyze_live", m);
    if (!res) {
      Moji.sorry();
      return;
    }
    if (!res.ok) {
      Moji.sorry();
      setStatus(
        (res.error || "失败") + (res.stderr ? " · " + String(res.stderr).slice(0, 120) : ""),
        "err"
      );
      // Keep cleared — do not leave a stale frame on failure.
      await call("clear_highlight");
      return;
    }
    Moji.easy();
    // First successful manual OCR → stay auto (freeze: never on cold launch).
    await call("note_manual_ocr_done", true, m);
    await syncAutoBtn();
    const inner = (res && res.result) || {};
    if (inner.skip_shop) {
      const pl =
        inner.procedure_level != null
          ? inner.procedure_level
          : res.procedure_level;
      setStatus(
        "规程等级 " +
          (pl != null ? pl : "?") +
          " · 已写入本局环境（难度选择，跳过商店） · " +
          (res.latency_ms || "?") +
          "ms",
        "ok"
      );
      return;
    }
    // analyze_live already applied glow; renderResult re-applies after paint of panel.
    await renderResult(res);
    const r = (res.result && res.result.resources) || {};
    const bits = [];
    bits.push(r.round != null ? "回合✓" : "回合手填");
    bits.push(r.gold != null ? "金币✓" : "金币手填");
    bits.push(r.dispatch_level != null ? "调度✓" : "调度手填");
    const t = res.timing || {};
    const side = t.sidecar || (res.result && res.result.timing) || {};
    const shell = t.shell || {};
    const timingBits = [];
    if (shell.capture_ms != null) timingBits.push("截屏" + shell.capture_ms);
    if (side.resources_ms != null) timingBits.push("资源" + side.resources_ms);
    if (side.enemy_panel_ms != null) timingBits.push("敌人" + side.enemy_panel_ms);
    if (side.shop_ms != null) timingBits.push("商店" + side.shop_ms);
    if (side.board_ms != null) timingBits.push("手牌" + side.board_ms);
    if (side.advise_ms != null) timingBits.push("决策" + side.advise_ms);
    if (shell.glow_ms != null) timingBits.push("高亮" + shell.glow_ms);
    const ep = (res.result && res.result.enemy_panel) || {};
    const enemyBit = (ep.names || []).length
      ? " · 敌人 " + (ep.names || []).join("/") +
        ((ep.trait_keys || []).length ? "→" + (ep.trait_keys || []).join("/") : "")
      : "";
    setStatus(
      "OCR 完成 · " +
        bits.join(" · ") +
        enemyBit +
        " · " +
        (res.latency_ms || shell.total_ms || "?") +
        "ms" +
        (timingBits.length ? " · " + timingBits.join("/") : ""),
      "ok"
    );
  }

  async function syncAutoBtn() {
    const st = await call("get_auto_ocr");
    const btn = $("btn-auto");
    if (!btn || !st) return;
    btn.classList.toggle("active", !!st.armed);
    btn.textContent = st.armed ? "自动·开" : "自动";
    btn.title = st.armed
      ? "自动识别已武装 · 再点关闭 · 周期≈" +
        (st.interval_sec || 4.5) +
        "s"
      : "武装自动识别（冷启动不自动；也可先手动 OCR 一次后保持自动）";
  }

  $("btn-live").addEventListener("click", () => runOcrLikeMock());

  $("btn-auto").addEventListener("click", async () => {
    const st = await call("get_auto_ocr");
    const next = !(st && st.armed);
    const res = await call("set_auto_ocr", next, metaFromForm());
    await syncAutoBtn();
    if (res && res.armed) {
      setStatus("自动识别已武装 · 等 prep/商店启发后周期 OCR", "ok");
    } else {
      setStatus("自动识别已关闭");
    }
  });

  $("btn-begin-match").addEventListener("click", async () => {
    Moji.thinking();
    setStatus("开始新一局 · 开日志并 OCR…");
    const res = await call("begin_match", "user", metaFromForm());
    if (!res || !res.ok) {
      Moji.sorry();
      setStatus((res && res.error) || "开始新一局失败", "err");
      return;
    }
    const armed = res.auto_armed ? " · 自动续写新文件夹" : "";
    setStatus(
      "新局 " + (res.match_id || "") + " · OCR 写入中" + armed,
      "ok"
    );
  });

  $("btn-end-match").addEventListener("click", async () => {
    const res = await call("end_current_match", "user");
    if (!res || !res.ok) {
      setStatus((res && res.error) || "结束一局失败（可能已空闲）", "err");
      return;
    }
    setStatus(
      "本局已结束 · " + (res.match_id || "") + " · 日志已封存（不删）",
      "ok"
    );
  });

  $("btn-lineup").addEventListener("click", async () => {
    Moji.thinking();
    setStatus("读阵容：标记→点击→面板/装备 OCR…");
    const res = await call("read_lineup_panel", metaFromForm());
    if (!res) {
      Moji.sorry();
      setStatus("读阵容调用失败", "err");
      return;
    }
    if (!res.ok) {
      Moji.sorry();
      setStatus(res.error || "读阵容失败", "err");
      return;
    }
    const n = res.named_count != null ? res.named_count : (res.board || []).length;
    const b = res.badge_count != null ? res.badge_count : "?";
    const eq = res.equipment || {};
    const eqN = Object.values(eq).reduce((a, v) => a + ((v && v.length) || 0), 0);
    Moji.happy();
    setStatus(
      res.message ||
        ("读阵容完成 · 标记 " + b + " · 点名 " + n + (eqN ? " · 装备 " + eqN : "")),
      "ok"
    );
  });

  $("btn-enemy").addEventListener("click", async () => {
    Moji.thinking();
    setStatus("读敌人：按 W 开放大镜 → 0.5s → OCR…");
    const res = await call("capture_enemy_panel", metaFromForm());
    if (!res) {
      Moji.sorry();
      return;
    }
    if (!res.ok) {
      Moji.sorry();
      setStatus(res.error || "读敌人失败", "err");
      return;
    }
    const p = res.enemy_panel || {};
    const names = p.names || [];
    const keys = p.trait_keys || [];
    const hk = res.hotkey || {};
    const hkBit = hk.focused
      ? "W✓"
      : hk.tapped
        ? "W(未聚焦游戏)"
        : "W失败";
    if (!names.length) {
      Moji.sorry();
      setStatus(
        "未识别到敌人名 · " +
          hkBit +
          " · 放大镜仍开着 · " +
          (res.latency_ms || "?") +
          "ms",
        "err"
      );
      return;
    }
    Moji.easy();
    setStatus(
      "本波敌人 " +
        names.join("、") +
        (keys.length ? " → " + keys.join("/") : "（无战术词条）") +
        " · " +
        hkBit +
        " · " +
        (res.latency_ms || "?") +
        "ms",
      "ok"
    );
  });

  $("btn-run-env").addEventListener("click", async () => {
    Moji.thinking();
    setStatus("录入本局：抓主屏 OCR → 阵容窗「本局环境」…");
    const res = await call("capture_run_env", metaFromForm());
    if (!res) {
      Moji.sorry();
      return;
    }
    if (!res.ok) {
      Moji.sorry();
      setStatus(res.error || "录入失败", "err");
      return;
    }
    if (res.env && res.env.target_bond) {
      $("bond").value = res.env.target_bond;
    }
    Moji.easy();
    // Result is pushed to roster companion via Api.push_run_env
    const pl = res.env && res.env.procedure_level;
    const screen = res.env && res.env.screen;
    const plBit =
      pl != null
        ? "规程等级 " + pl + (screen === "difficulty_select" ? "（难度选择）" : "") + " · "
        : "";
    setStatus(
      "本局已写入 · " + plBit + "见阵容窗 · " + (res.latency_ms || "?") + "ms",
      "ok"
    );
  });

  $("btn-mock").addEventListener("click", async () => {
    setStatus("加载 Mock…");
    const res = await call("load_mock");
    if (!res) return;
    if (res.ok === false) {
      setStatus(res.error || "Mock 失败", "err");
      return;
    }
    renderResult(res.result || res);
    setStatus("Mock 已加载（非 OCR）", "ok");
  });

  $("btn-state").addEventListener("click", async () => {
    setStatus("调用内核 --state …");
    const res = await call("analyze_state", metaFromForm());
    if (!res) return;
    if (!res.ok) {
      setStatus((res.error || "失败") + (res.stderr ? " · " + res.stderr.slice(0, 120) : ""), "err");
      return;
    }
    renderResult(res);
    setStatus("State 完成 · " + (res.latency_ms || "?") + "ms", "ok");
  });

  $("btn-shot").addEventListener("click", async () => {
    Moji.thinking();
    setStatus("选择截图文件…");
    const res = await call("analyze_shot", metaFromForm());
    if (!res) {
      Moji.sorry();
      return;
    }
    if (res.cancelled) {
      Moji.idle();
      setStatus("已取消");
      return;
    }
    if (!res.ok) {
      Moji.sorry();
      setStatus((res.error || "失败") + (res.stderr ? " · " + res.stderr.slice(0, 120) : ""), "err");
      return;
    }
    Moji.easy();
    renderResult(res);
    setStatus("文件 OCR 完成 · " + (res.latency_ms || "?") + "ms", "ok");
  });

  function setPanelCollapsed(on) {
    document.body.classList.toggle("collapsed", !!on);
    const btn = $("btn-hide");
    if (btn) {
      btn.textContent = on ? "展" : "隐";
      btn.title = on ? "展开参谋窗" : "折叠内容（不关窗）· Ctrl+Shift+W";
    }
  }
  window.__panel_set_collapsed = setPanelCollapsed;

  $("btn-hide").addEventListener("click", async () => {
    const collapsed = await call("toggle_panel_collapsed");
    setPanelCollapsed(!!collapsed);
  });
  $("btn-interact").addEventListener("click", async () => {
    const on = await call("toggle_interact");
    $("btn-interact").classList.toggle("active", !!on);
    setStatus(on ? "可交互（穿透关）" : "穿透开 · 标题栏仍可点交互/隐");
  });

  // Title-bar drag via SetWindowPos. WinForms+WebView2 ignores WM_NCLBUTTONDOWN.
  // Prefer pywebviewMoveWindow (same path as EdgeChromium easy_drag); fall back
  // to Api.drag_move. Also mark .pywebview-drag-region for the injected selector.
  (function bindChromeDrag() {
    const bar = $("drag-bar");
    if (!bar) return;
    bar.classList.add("pywebview-drag-region");
    let dragging = false;
    let ox = 0;
    let oy = 0;
    const moveTo = (x, y) => {
      // Prefer Api.drag_move → HWND SetWindowPos. Live CDP check: pywebviewMoveWindow
      // returns ok but does not move this WinForms+TOPMOST host; hwnd path does.
      if (window.pywebview && window.pywebview.api && window.pywebview.api.drag_move) {
        window.pywebview.api.drag_move("panel", x, y);
        return;
      }
      if (window.pywebview && typeof window.pywebview._jsApiCallback === "function") {
        window.pywebview._jsApiCallback("pywebviewMoveWindow", [x, y], "move");
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
        window.pywebview.api.end_drag("panel");
      }
    };
    bar.addEventListener("pointerdown", (ev) => {
      if (ev.button !== 0) return;
      const t = ev.target;
      if (t && t.closest && t.closest(".bar-actions, button, a, input, select, textarea, label")) {
        return;
      }
      ev.preventDefault();
      dragging = true;
      ox = ev.clientX;
      oy = ev.clientY;
      try { bar.setPointerCapture(ev.pointerId); } catch (_) {}
      call("start_drag", "panel");
      window.addEventListener("pointermove", onMove, true);
      window.addEventListener("pointerup", onUp, true);
      window.addEventListener("mousemove", onMove, true);
      window.addEventListener("mouseup", onUp, true);
    });
  })();

  window.addEventListener("pywebviewready", async () => {
    const cfg = await call("get_defaults");
    if (cfg) {
      if (cfg.round != null) $("round").value = cfg.round;
      if (cfg.gold != null) $("gold").value = cfg.gold;
      if (cfg.dispatch_level != null) $("dispatch").value = cfg.dispatch_level;
      if (cfg.target_bond) $("bond").value = cfg.target_bond;
    }
    // 本局环境展示在阵容 companion；此处只同步目标羁绊手填
    const envRes = await call("get_run_env");
    if (envRes && envRes.ok && envRes.env && envRes.env.target_bond && !$("bond").value) {
      $("bond").value = envRes.env.target_bond;
    }
    await syncAutoBtn();
    const logHint =
      cfg && cfg.op_log_match_id
        ? " · 日志 " + cfg.op_log_match_id
        : "";
    setStatus(
      "就绪 · 「开始新一局」/「结束一局」日志" + logHint
    );
  });

  window.__weishu_render = function (envelope) {
    if (!envelope) return;
    if (!envelope.ok) {
      Moji.sorry();
      setStatus(envelope.error || "失败", "err");
      call("clear_highlight");
      return;
    }
    Moji.easy();
    const inner = envelope.result || {};
    if (inner.skip_shop) {
      const pl =
        inner.procedure_level != null
          ? inner.procedure_level
          : envelope.procedure_level;
      setStatus(
        "规程等级 " +
          (pl != null ? pl : "?") +
          " · 已写入本局环境（难度选择） · " +
          (envelope.latency_ms || "?") +
          "ms",
        "ok"
      );
      return;
    }
    Promise.resolve(renderResult(envelope)).then(function () {
      setStatus("识别完成 · " + (envelope.latency_ms || "?") + "ms", "ok");
    });
  };
})();
