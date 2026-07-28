(() => {
  "use strict";

  const REFRESH_INTERVAL_MS = 5 * 60 * 1000;
  const DATA_URL = "./data/news.json";
  const GROUP_LABELS = {
    national: "国内主要紙",
    local: "地元紙",
    wire: "通信社",
    public: "公共放送",
    全国紙: "国内主要紙",
    地元紙: "地元紙",
    通信社: "通信社",
    公共放送: "公共放送",
  };

  const state = {
    items: [],
    trackedSources: [],
    sourceCounts: {},
    keyword: "",
    source: "",
    sort: "newest",
    loading: false,
    loadedAt: null,
  };

  const elements = {
    articleCount: document.querySelector("#article-count"),
    sourceCount: document.querySelector("#source-count"),
    updatedAt: document.querySelector("#updated-at"),
    refreshStatus: document.querySelector("#refresh-status"),
    sourceButtons: document.querySelector("#source-buttons"),
    articleList: document.querySelector("#article-list"),
    resultSummary: document.querySelector("#result-summary"),
    keyword: document.querySelector("#keyword"),
    sourceSelect: document.querySelector("#source-select"),
    sortSelect: document.querySelector("#sort-select"),
    clearFilters: document.querySelector("#clear-filters"),
    emptyState: document.querySelector("#empty-state"),
    errorState: document.querySelector("#error-state"),
    retryButton: document.querySelector("#retry-button"),
    filterForm: document.querySelector("#filter-form"),
  };

  const escapeHtml = (value) =>
    String(value ?? "")
      .replaceAll("&", "&amp;")
      .replaceAll("<", "&lt;")
      .replaceAll(">", "&gt;")
      .replaceAll('"', "&quot;")
      .replaceAll("'", "&#039;");

  const safeUrl = (value) => {
    try {
      const url = new URL(String(value));
      return ["https:", "http:"].includes(url.protocol) ? url.href : "#";
    } catch {
      return "#";
    }
  };

  const parseDate = (value) => {
    if (!value) return null;
    const date = new Date(value);
    return Number.isNaN(date.getTime()) ? null : date;
  };

  const formatDateTime = (value, includeYear = true) => {
    const date = parseDate(value);
    if (!date) return "日時不明";

    return new Intl.DateTimeFormat("ja-JP", {
      timeZone: "Asia/Tokyo",
      year: includeYear ? "numeric" : undefined,
      month: "2-digit",
      day: "2-digit",
      hour: "2-digit",
      minute: "2-digit",
      hour12: false,
    }).format(date);
  };

  const normalizeTrackedSources = (data) => {
    const declared = Array.isArray(data.tracked_sources) ? data.tracked_sources : [];
    const sourceNames = declared
      .map((source) => (typeof source === "string" ? source : source?.name ?? source?.label))
      .filter(Boolean);
    const itemSources = (Array.isArray(data.items) ? data.items : [])
      .map((item) => item?.source)
      .filter(Boolean);

    return [...new Set([...sourceNames, ...itemSources])];
  };

  const countSources = (items) => {
    const counts = {};
    for (const item of items) {
      if (!item.source) continue;
      counts[item.source] = (counts[item.source] ?? 0) + 1;
    }
    return counts;
  };

  const setLoadingMessage = (message) => {
    elements.refreshStatus.textContent = message;
  };

  async function loadNews({ manual = false } = {}) {
    if (state.loading) return;
    state.loading = true;
    elements.errorState.hidden = true;

    if (manual || !state.loadedAt) {
      setLoadingMessage("最新データを確認しています");
    }

    try {
      const response = await fetch(`${DATA_URL}?t=${Date.now()}`, {
        cache: "no-store",
        headers: { Accept: "application/json" },
      });
      if (!response.ok) throw new Error(`HTTP ${response.status}`);

      const data = await response.json();
      if (!Array.isArray(data.items)) throw new Error("items is not an array");

      state.items = data.items.filter(
        (item) => item && typeof item.title === "string" && typeof item.source === "string",
      );
      state.trackedSources = normalizeTrackedSources(data);
      state.sourceCounts = {
        ...countSources(state.items),
        ...(data.source_counts && typeof data.source_counts === "object"
          ? data.source_counts
          : {}),
      };
      state.loadedAt = new Date();

      const updatedValue = data.updated_at || data.updated_at_jst;
      elements.articleCount.textContent = Number.isFinite(Number(data.article_count))
        ? Number(data.article_count).toLocaleString("ja-JP")
        : state.items.length.toLocaleString("ja-JP");
      elements.sourceCount.textContent = Number.isFinite(Number(data.source_count))
        ? Number(data.source_count).toLocaleString("ja-JP")
        : new Set(state.items.map((item) => item.source)).size.toLocaleString("ja-JP");
      elements.updatedAt.textContent = formatDateTime(updatedValue);
      setLoadingMessage(`画面確認 ${formatDateTime(state.loadedAt.toISOString(), false)}`);

      renderSourceControls();
      renderArticles();
    } catch (error) {
      console.error("Failed to load news data:", error);
      elements.articleList.replaceChildren();
      elements.articleList.setAttribute("aria-busy", "false");
      elements.emptyState.hidden = true;
      elements.errorState.hidden = false;
      elements.resultSummary.textContent = "読み込みに失敗しました";
      setLoadingMessage("データ取得エラー");
    } finally {
      state.loading = false;
    }
  }

  function renderSourceControls() {
    const allCount = state.items.length;
    const sources = [...state.trackedSources].sort((a, b) =>
      a.localeCompare(b, "ja"),
    );

    const buttonMarkup = [
      sourceButtonMarkup("", "すべて", allCount),
      ...sources.map((source) =>
        sourceButtonMarkup(source, source, Number(state.sourceCounts[source] ?? 0)),
      ),
    ].join("");
    elements.sourceButtons.innerHTML = buttonMarkup;

    const currentOptions = new Set(
      [...elements.sourceSelect.options].map((option) => option.value),
    );
    const expectedOptions = new Set(["", ...sources]);
    const optionsChanged =
      currentOptions.size !== expectedOptions.size ||
      [...expectedOptions].some((source) => !currentOptions.has(source));

    if (optionsChanged) {
      elements.sourceSelect.innerHTML = [
        '<option value="">すべての媒体</option>',
        ...sources.map(
          (source) =>
            `<option value="${escapeHtml(source)}">${escapeHtml(source)}</option>`,
        ),
      ].join("");
    }

    if (state.source && !expectedOptions.has(state.source)) {
      state.source = "";
    }
    elements.sourceSelect.value = state.source;
  }

  function sourceButtonMarkup(value, label, count) {
    const isActive = state.source === value;
    return `
      <button
        class="source-button${isActive ? " is-active" : ""}"
        type="button"
        data-source="${escapeHtml(value)}"
        aria-pressed="${isActive ? "true" : "false"}"
      >
        <span>${escapeHtml(label)}</span>
        <span class="source-button__count">${Number(count).toLocaleString("ja-JP")}</span>
      </button>
    `;
  }

  function getVisibleItems() {
    const keyword = state.keyword.trim().toLocaleLowerCase("ja");

    return state.items
      .filter((item) => {
        const matchesSource = !state.source || item.source === state.source;
        const searchText = `${item.title} ${item.source}`.toLocaleLowerCase("ja");
        const matchesKeyword = !keyword || searchText.includes(keyword);
        return matchesSource && matchesKeyword;
      })
      .sort((a, b) => {
        if (state.sort === "source") {
          const bySource = a.source.localeCompare(b.source, "ja");
          if (bySource !== 0) return bySource;
        }

        const left = parseDate(a.published_at)?.getTime() ?? 0;
        const right = parseDate(b.published_at)?.getTime() ?? 0;
        return state.sort === "oldest" ? left - right : right - left;
      });
  }

  function renderArticles() {
    const visibleItems = getVisibleItems();
    const hasFilters = Boolean(state.keyword.trim() || state.source);

    elements.articleList.setAttribute("aria-busy", "false");
    elements.errorState.hidden = true;
    elements.emptyState.hidden = visibleItems.length > 0;
    elements.resultSummary.textContent = hasFilters
      ? `${state.items.length.toLocaleString("ja-JP")}件中 ${visibleItems.length.toLocaleString("ja-JP")}件を表示`
      : `${visibleItems.length.toLocaleString("ja-JP")}件の報道`;

    if (visibleItems.length === 0) {
      elements.articleList.replaceChildren();
      return;
    }

    elements.articleList.innerHTML = visibleItems.map(articleMarkup).join("");
  }

  function articleMarkup(item) {
    const group = GROUP_LABELS[item.source_group] || item.source_group || "報道";
    const published = formatDateTime(item.published_at);
    const url = safeUrl(item.url);
    const linkLabel = `${item.title}（${item.source}の記事を新しいタブで開く）`;

    return `
      <article class="article-card">
        <div class="article-card__body">
          <div class="article-card__meta">
            <time datetime="${escapeHtml(item.published_at || "")}">${escapeHtml(published)}</time>
            <span class="article-card__group">${escapeHtml(group)}</span>
          </div>
          <h3>
            <a
              class="article-card__link"
              href="${escapeHtml(url)}"
              target="_blank"
              rel="noopener noreferrer"
              aria-label="${escapeHtml(linkLabel)}"
            >${escapeHtml(item.title)}</a>
          </h3>
        </div>
        <div class="article-card__source">
          <span>Source</span>
          <strong>${escapeHtml(item.source)}</strong>
          <i aria-hidden="true"></i>
        </div>
      </article>
    `;
  }

  function setSource(source) {
    state.source = source;
    elements.sourceSelect.value = source;
    renderSourceControls();
    renderArticles();
  }

  function clearFilters() {
    state.keyword = "";
    state.source = "";
    state.sort = "newest";
    elements.keyword.value = "";
    elements.sourceSelect.value = "";
    elements.sortSelect.value = "newest";
    renderSourceControls();
    renderArticles();
    elements.keyword.focus();
  }

  elements.filterForm.addEventListener("submit", (event) => event.preventDefault());

  elements.keyword.addEventListener("input", (event) => {
    state.keyword = event.target.value;
    renderArticles();
  });

  elements.sourceSelect.addEventListener("change", (event) => {
    setSource(event.target.value);
  });

  elements.sortSelect.addEventListener("change", (event) => {
    state.sort = event.target.value;
    renderArticles();
  });

  elements.sourceButtons.addEventListener("click", (event) => {
    const button = event.target.closest("[data-source]");
    if (!button) return;
    setSource(button.dataset.source || "");
  });

  elements.clearFilters.addEventListener("click", clearFilters);
  elements.retryButton.addEventListener("click", () => loadNews({ manual: true }));

  document.addEventListener("visibilitychange", () => {
    if (
      document.visibilityState === "visible" &&
      state.loadedAt &&
      Date.now() - state.loadedAt.getTime() >= REFRESH_INTERVAL_MS
    ) {
      loadNews();
    }
  });

  window.addEventListener("focus", () => {
    if (
      state.loadedAt &&
      Date.now() - state.loadedAt.getTime() >= REFRESH_INTERVAL_MS
    ) {
      loadNews();
    }
  });

  window.setInterval(() => {
    if (document.visibilityState === "visible") loadNews();
  }, REFRESH_INTERVAL_MS);

  loadNews();
})();
