const DEFAULT_API_BASE = "http://127.0.0.1:8000";
const POLL_MS = 1500;
const PAGE_SETTLE_MS = 8000;
const EXTRACTION_ATTEMPTS = 8;
const EXTRACTION_RETRY_MS = 3000;
const WAKE_ALARM = "email-article-analyzer-poll";
let pollInFlight = false;
let pollTimer = null;

function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

async function apiFetch(path, options = {}) {
  const apiBase = await getApiBase();
  const password = await getBackendPassword();
  const headers = new Headers(options.headers || {});
  if (password) {
    headers.set("X-Email-Article-Analyzer-Password", password);
  }
  const response = await fetch(`${apiBase}${path}`, { ...options, headers });
  if (!response.ok) {
    throw new Error(`${response.status} ${response.statusText}`);
  }
  return response.json();
}

async function getApiBase() {
  const stored = await chrome.storage.local.get({ apiBase: DEFAULT_API_BASE });
  return normalizeApiBase(stored.apiBase);
}

async function getBackendPassword() {
  const stored = await chrome.storage.local.get({ backendPassword: "" });
  return String(stored.backendPassword || "").trim();
}

function normalizeApiBase(value) {
  const trimmed = String(value || DEFAULT_API_BASE).trim().replace(/\/+$/, "");
  if (!trimmed) {
    return DEFAULT_API_BASE;
  }
  return trimmed;
}

function extractArticleText() {
  function readableElementText(element) {
    if (!element) {
      return "";
    }
    const innerText = String(element.innerText || "").trim();
    const textContent = String(element.textContent || "").trim();
    if (innerText.length >= 100) {
      return innerText;
    }
    return textContent.length > innerText.length ? textContent : innerText;
  }

  function richElementText(element) {
    if (!element) {
      return "";
    }
    const innerText = String(element.innerText || "").trim();
    const textContent = String(element.textContent || "").trim();
    return textContent.length > innerText.length ? textContent : innerText;
  }

  function compactLines(value) {
    return String(value || "")
      .split(/\n+/)
      .map((line) => line.trim())
      .filter(Boolean);
  }

  function valueAfterLabel(lines, label, count) {
    const index = lines.findIndex((line) => {
      const normalizedLine = line.toLowerCase().replace(/:$/, "");
      const normalizedLabel = label.toLowerCase().replace(/:$/, "");
      return normalizedLine === normalizedLabel;
    });
    if (index < 0) {
      return null;
    }
    const values = lines.slice(index + 1, index + 1 + count).filter(Boolean);
    return values.length === count ? values : null;
  }

  function valueAfterLabels(lines, labels, count) {
    for (const label of labels) {
      const value = valueAfterLabel(lines, label, count);
      if (value) {
        return value;
      }
    }
    return null;
  }

  function valueAfterLinePattern(lines, pattern, count) {
    const index = lines.findIndex((line) => pattern.test(line));
    if (index < 0) {
      return null;
    }
    const values = lines.slice(index + 1, index + 1 + count).filter(Boolean);
    return values.length === count ? values : null;
  }

  function isSeekingAlphaRatingPage(url) {
    return /https?:\/\/(www\.)?seekingalpha\.com\/symbol\/[^/]+\/ratings/i.test(url || "");
  }

  function isZacksQuotePage(url) {
    return /https?:\/\/(www\.)?zacks\.com\/stock\/(?:quote|research)\/[^/?#]+/i.test(url || "");
  }

  function seekingAlphaRatingLines(value) {
    const lines = compactLines(value);
    const normalized = [];
    const quant =
      valueAfterLabel(lines, "Quant Rating", 2) ||
      valueAfterLinePattern(lines, /^[A-Z.-]+\s+Quant Rating$/i, 2);
    if (quant) {
      normalized.push(`SA Quant Rating ${quant.join(" ")}`);
    }
    const analysts = valueAfterLabels(
      lines,
      ["Analysts Rating", "SA Analysts' Rating", "SA Analysts Rating", "Author Rating", "Authors Rating"],
      2,
    );
    if (analysts) {
      normalized.push(`SA Analysts Rating ${analysts.join(" ")}`);
    }
    const wallStreet = valueAfterLabels(
      lines,
      [
        "Wall Street Rating",
        "Wall St. Analysts' Rating",
        "Wall St. Analysts Rating",
        "Sell Side Rating",
        "Sell Side Ratings",
      ],
      2,
    );
    if (wallStreet) {
      normalized.push(`Wall Street Rating ${wallStreet.join(" ")}`);
    }
    const target = valueAfterLabels(
      lines,
      ["Wall Street Price Target", "Sell Side Price Target", "Average Price Target"],
      1,
    );
    if (target) {
      normalized.push(`Wall Street price target ${target[0]}`);
    }
    return normalized;
  }

  function zacksRatingLines(value) {
    const lines = compactLines(value);
    const normalized = [];
    const rank = valueAfterLabel(lines, "Zacks Rank", 1);
    if (rank) {
      normalized.push(normalizeZacksRankLine(rank[0]));
    }
    const compactValue = String(value || "").replace(/\s+/g, " ");
    const inlineRank = compactValue.match(/Zacks Rank:?\s*(?:More Info)?\s*(?:#?\s*)?([1-5])\s*[-(]\s*(Strong Buy|Buy|Hold|Sell|Strong Sell)\)?/i);
    if (inlineRank) {
      normalized.push(`Zacks Rank #${inlineRank[1]} (${inlineRank[2]})`);
    }
    const broker = valueAfterLabel(lines, "Average Broker Recommendation", 1);
    if (broker) {
      normalized.push(`Average Broker Recommendation ${broker[0]}`);
    }
    const target = valueAfterLabel(lines, "Price Target", 1);
    if (target) {
      normalized.push(`Price Target ${target[0]}`);
    }
    const average = valueAfterLabel(lines, "Average Price Target", 1);
    if (average) {
      normalized.push(`Average Price Target ${average[0]}`);
    }
    const high = valueAfterLabel(lines, "Highest Price Target", 1);
    if (high) {
      normalized.push(`Highest Price Target ${high[0]}`);
    }
    const low = valueAfterLabel(lines, "Lowest Price Target", 1);
    if (low) {
      normalized.push(`Lowest Price Target ${low[0]}`);
    }
    const upside = valueAfterLabel(lines, "Upside to Average Price Target", 1);
    if (upside) {
      normalized.push(`Upside to Average Price Target ${upside[0]}`);
    }
    const lastClose = valueAfterLabel(lines, "Last Close", 1);
    if (lastClose) {
      normalized.push(`Last Close ${lastClose[0]}`);
    }
    return normalized;
  }

  function normalizeZacksRankLine(value) {
    const textValue = String(value || "").trim();
    const compactRank = textValue.match(/^#?\s*([1-5])\s*[-(]\s*(Strong Buy|Buy|Hold|Sell|Strong Sell)\)?$/i);
    if (compactRank) {
      return `Zacks Rank #${compactRank[1]} (${compactRank[2]})`;
    }
    return `Zacks Rank ${textValue}`;
  }

  function zacksDomRatingText(url) {
    if (!isZacksQuotePage(url) || typeof document.querySelectorAll !== "function") {
      return "";
    }
    const selector = "[id*='rank' i], [class*='rank' i], [aria-label*='rank' i], [title*='rank' i]";
    const lines = [];
    const seen = new Set();
    const elements = Array.from(document.querySelectorAll(selector) || []).slice(0, 80);
    elements.forEach((element) => {
      const candidates = [
        readableElementText(element),
        typeof element.getAttribute === "function" ? element.getAttribute("aria-label") : "",
        typeof element.getAttribute === "function" ? element.getAttribute("title") : "",
      ];
      Array.from(element.attributes || []).forEach((attribute) => {
        if (/rank/i.test(attribute.name) || /rank|strong buy|buy|hold|sell/i.test(attribute.value || "")) {
          candidates.push(attribute.value);
        }
      });
      candidates.forEach((candidate) => {
        const value = String(candidate || "").replace(/\s+/g, " ").trim();
        if (!value || seen.has(value)) {
          return;
        }
        seen.add(value);
        const explicit = value.match(/Zacks Rank\s*(?:More Info)?\s*(?:#?\s*)?([1-5])\s*[-(]\s*(Strong Buy|Buy|Hold|Sell|Strong Sell)\)?/i);
        const compact = value.match(/^#?\s*([1-5])\s*[-(]\s*(Strong Buy|Buy|Hold|Sell|Strong Sell)\)?$/i);
        if (explicit) {
          lines.push(`Zacks Rank #${explicit[1]} (${explicit[2]})`);
        } else if (compact) {
          lines.push(`Zacks Rank #${compact[1]} (${compact[2]})`);
        }
      });
    });
    return lines.join("\n");
  }

  function enrichSourceRatingText(url, value) {
    const normalizedLines = [];
    if (isSeekingAlphaRatingPage(url)) {
      normalizedLines.push(...seekingAlphaRatingLines(value));
    }
    if (isZacksQuotePage(url)) {
      normalizedLines.push(...zacksRatingLines(value));
    }
    if (!normalizedLines.length) {
      return value;
    }
    return `${normalizedLines.join("\n")}\n${value}`.trim();
  }

  function sourceDataLinesFromValue(rootName, value, interestingPattern = null) {
    const lines = [];
    const seen = new Set();
    const interesting = interestingPattern || /(rating|score|rank|target|quant|author|sell|side|wall|analyst|forecast)/i;
    function walk(current, path) {
      if (current === null || current === undefined || lines.length >= 300) {
        return;
      }
      if (typeof current === "object") {
        if (seen.has(current)) {
          return;
        }
        seen.add(current);
        if (Array.isArray(current)) {
          current.slice(0, 100).forEach((item, index) => walk(item, `${path}[${index}]`));
          return;
        }
        Object.entries(current).forEach(([key, child]) => {
          const nextPath = `${path}.${key}`;
          if (interesting.test(nextPath)) {
            walk(child, nextPath);
          } else if (typeof child === "object" && child !== null) {
            walk(child, nextPath);
          }
        });
        return;
      }
      const textValue = String(current).trim();
      if (!textValue || textValue.length > 200) {
        return;
      }
      if (interesting.test(path) || /(Strong Buy|Buy|Hold|Sell|Strong Sell|Neutral|Outperform|Underperform|\$[0-9])/i.test(textValue)) {
        lines.push(`SA_DATA ${path} = ${textValue}`);
      }
    }
    walk(value, rootName);
    return lines;
  }

  function parsedScriptDataLines(interestingPattern = null) {
    if (typeof document.querySelectorAll !== "function") {
      return [];
    }
    const lines = [];
    const scripts = Array.from(document.querySelectorAll("script") || []).slice(0, 80);
    scripts.forEach((script, index) => {
      if (lines.length >= 300) {
        return;
      }
      const raw = String(script.textContent || "").trim();
      if (!raw || raw.length > 3000000) {
        return;
      }
      const interesting = interestingPattern || /(rating|score|rank|target|quant|author|sell|side|wall|analyst|forecast)/i;
      if (!interesting.test(raw)) {
        return;
      }
      const candidates = [];
      if (/^\s*[{[]/.test(raw)) {
        candidates.push(raw);
      }
      const nextDataMatch = raw.match(/<script[^>]+id=["']__NEXT_DATA__["'][^>]*>([\s\S]*?)<\/script>/i);
      if (nextDataMatch) {
        candidates.push(nextDataMatch[1]);
      }
      candidates.forEach((candidate) => {
        try {
          const parsed = JSON.parse(candidate);
          lines.push(...sourceDataLinesFromValue(`SCRIPT_DATA[${index}]`, parsed, interesting));
        } catch (_error) {
          // Ignore non-JSON scripts; SA mixes executable scripts with data scripts.
        }
      });
    });
    return lines;
  }

  function sourceDataText(url) {
    if (!/https?:\/\/(www\.)?seekingalpha\.com\/symbol\//i.test(url || "")) {
      return "";
    }
    const researchPage = /\/(?:income-statement|cash-flow-statement|valuation|growth|profitability|momentum|earnings|peers)(?:\/|$)/i.test(url || "");
    const interesting = researchPage
      ? /(financial|income|cash|flow|revenue|period|fiscal|ttm|capital|expenditure|operating|metric|value|statement|currency)/i
      : /(rating|score|rank|target|quant|author|sell|side|wall|analyst|forecast)/i;
    const lines = [];
    for (const [name, value] of [
      ["SSR_DATA", window.SSR_DATA],
      ["__NEXT_DATA__", window.__NEXT_DATA__],
      ["__APOLLO_STATE__", window.__APOLLO_STATE__],
      ["__PRELOADED_STATE__", window.__PRELOADED_STATE__],
      ["__INITIAL_STATE__", window.__INITIAL_STATE__],
    ]) {
      if (typeof value !== "undefined") {
        lines.push(...sourceDataLinesFromValue(name, value, interesting));
      }
    }
    lines.push(...parsedScriptDataLines(interesting));
    return lines.join("\n");
  }

  function seekingAlphaResearchDomText(url) {
    if (!/https?:\/\/(www\.)?seekingalpha\.com\/symbol\/[^/]+\/(?:income-statement|cash-flow-statement)/i.test(url || "") || typeof document.querySelectorAll !== "function") {
      return "";
    }
    const lines = [];
    const seen = new Set();
    const selectors = ["table", "[role='table']", "[role='grid']", "[data-test-id*='financial' i]", "[class*='financial' i]"];
    selectors.forEach((selector) => {
      Array.from(document.querySelectorAll(selector) || []).slice(0, 20).forEach((element) => {
        const value = richElementText(element).trim();
        if (value.length >= 50 && /(?:TTM|Fiscal Year|Total Revenue|Cash from Operations|Operating Cash Flow)/i.test(value) && !seen.has(value)) {
          seen.add(value);
          lines.push(`SA_STATEMENT\n${value}`);
        }
      });
    });
    Array.from(document.querySelectorAll("iframe") || []).slice(0, 10).forEach((frame) => {
      try {
        const value = richElementText(frame.contentDocument?.body).trim();
        if (value.length >= 50 && /(?:TTM|Fiscal Year|Total Revenue|Cash from Operations|Operating Cash Flow)/i.test(value) && !seen.has(value)) {
          seen.add(value);
          lines.push(`SA_STATEMENT\n${value}`);
        }
      } catch (_error) {
        // Cross-origin frames are not readable; continue with the main document.
      }
    });
    return lines.join("\n");
  }

  function investingSearchResultText(url) {
    if (!/https?:\/\/(www\.)?investing\.com\/search\//i.test(url || "") || typeof document.querySelectorAll !== "function") {
      return "";
    }
    const lines = [];
    const seen = new Set();
    const scopedSelector = [
      ".js-inner-all-results-quotes-wrapper a[href*='/equities/']",
      ".js-inner-all-results-quotes-wrapper a[href*='/etfs/']",
      ".searchResultsMain .quatesTable a[href*='/equities/']",
      ".searchResultsMain .quatesTable a[href*='/etfs/']",
    ].join(", ");
    let anchors = Array.from(document.querySelectorAll(scopedSelector) || []);
    if (!anchors.length) {
      anchors = Array.from(document.querySelectorAll("a.js-inner-all-results-quote-item[href*='/equities/'], a.js-inner-all-results-quote-item[href*='/etfs/']") || []);
    }
    anchors = anchors.slice(0, 150);
    anchors.forEach((anchor) => {
      const href = typeof anchor.getAttribute === "function" ? String(anchor.getAttribute("href") || "").trim() : "";
      const label = readableElementText(anchor).replace(/\s+/g, " ").trim();
      if (!href || !label) {
        return;
      }
      const line = `INVESTING_RESULT ${label} | ${href}`;
      if (!seen.has(line)) {
        seen.add(line);
        lines.push(line);
      }
    });
    return lines.join("\n");
  }

  function equityNewsListingText(url) {
    if (typeof document.querySelectorAll !== "function") {
      return "";
    }
    const isSa = /https?:\/\/(www\.)?seekingalpha\.com\/symbol\/[^/]+\/(?:news|analysis)/i.test(url || "");
    const isInvesting = /https?:\/\/(www\.)?investing\.com\/(?:equities|etfs)\/[^/?#]+-(?:news|opinion)/i.test(url || "");
    if (!isSa && !isInvesting) {
      return "";
    }
    const pageType = /(?:\/analysis|\-opinion)(?:[/?#]|$)/i.test(url || "") ? "analysis" : "news";
    const provider = isSa ? "seeking_alpha" : "investing_pro";
    const hrefPattern = isSa
      ? (pageType === "analysis" ? /\/article\//i : /\/news\//i)
      : (pageType === "analysis" ? /\/analysis\//i : /\/news\//i);
    const lines = [];
    const seen = new Set();
    const cards = Array.from(document.querySelectorAll("article, [role='article']") || []).slice(0, 50);
    cards.forEach((card) => {
      const anchors = Array.from(card.querySelectorAll("a[href]") || []);
      const primary = anchors.find((anchor) => hrefPattern.test(String(anchor.getAttribute("href") || "")) && readableElementText(anchor).length >= 8);
      if (!primary) {
        return;
      }
      let itemUrl = "";
      try {
        itemUrl = new URL(primary.getAttribute("href"), window.location.href).toString().split("#", 1)[0];
      } catch (_error) {
        return;
      }
      if (!itemUrl || seen.has(itemUrl)) {
        return;
      }
      const title = readableElementText(primary).replace(/\s+/g, " ").trim();
      if (!title) {
        return;
      }
      const cardText = readableElementText(card).replace(/\s+/g, " ").trim();
      const timeElement = card.querySelector("time");
      const publishedAt = String(
        timeElement?.getAttribute("datetime") || timeElement?.textContent ||
        (cardText.match(/(?:Mon|Tue|Wed|Thu|Fri|Sat|Sun),?\s+[A-Z][a-z]{2}\s+\d{1,2}(?:,\s+20\d{2})?/i) || [""])[0]
      ).trim();
      const authorAnchor = anchors.find((anchor) => {
        const href = String(anchor.getAttribute("href") || "");
        return isSa ? /\/author\//i.test(href) : !hrefPattern.test(href) && /(?:\/members\/|\/brokers\/?$)/i.test(href);
      });
      const author = readableElementText(authorAnchor).replace(/\s+/g, " ").trim();
      const ratingMatch = cardText.match(/Author['’]s rating:\s*(Strong Buy|Buy|Hold|Sell|Strong Sell)/i);
      const paragraphs = Array.from(card.querySelectorAll("p") || [])
        .map((paragraph) => readableElementText(paragraph).replace(/\s+/g, " ").trim())
        .filter((value) => value && value !== title);
      const excerpt = (paragraphs[0] || "").slice(0, 500);
      seen.add(itemUrl);
      lines.push(`EQUITY_NEWS_ITEM ${JSON.stringify({
        provider,
        content_type: pageType,
        title,
        url: itemUrl,
        published_at: publishedAt,
        author,
        author_rating: ratingMatch ? ratingMatch[1] : "",
        excerpt,
      })}`);
    });
    return lines.join("\n");
  }

  function zacksInsiderTransactionsText(url) {
    if (!/https?:\/\/(www\.)?zacks\.com\/stock\/research\/[^/?#]+\/insider-transactions/i.test(url || "") || typeof document.querySelectorAll !== "function") {
      return "";
    }
    const lines = [];
    const seen = new Set();
    const normalizeDate = (value) => {
      const match = String(value || "").trim().match(/^(\d{1,2})\/(\d{1,2})\/(\d{2}|\d{4})$/);
      if (!match) {
        return String(value || "").trim();
      }
      const year = match[3].length === 2 ? 2000 + Number(match[3]) : Number(match[3]);
      return `${year}-${String(Number(match[1])).padStart(2, "0")}-${String(Number(match[2])).padStart(2, "0")}`;
    };
    Array.from(document.querySelectorAll("table") || []).slice(0, 30).forEach((table) => {
      const header = Array.from(table.querySelectorAll("thead th, thead td") || [])
        .map((cell) => readableElementText(cell).replace(/’/g, "'").replace(/\s+/g, " ").trim())
        .join(" | ");
      if (!/Filer['â€™]?s name/i.test(header) || !/Tran(?:saction)?\s+Type/i.test(header) || !/Total Shares Owned/i.test(header)) {
        return;
      }
      Array.from(table.querySelectorAll("tbody tr") || []).slice(0, 200).forEach((row) => {
        const cells = Array.from(row.querySelectorAll("th, td") || [])
          .map((cell) => readableElementText(cell).replace(/\s+/g, " ").trim());
        if (cells.length < 10 || !/^[AD][A-Z]$/i.test(cells[3])) {
          return;
        }
        const key = `${cells[0]}|${cells[2]}|${cells[3]}|${cells[6]}|${cells[7]}`;
        if (seen.has(key)) {
          return;
        }
        seen.add(key);
        lines.push(`EQUITY_INSIDER_TXN ${JSON.stringify({
          provider: "zacks",
          insider_name: cells[0],
          relationship: cells[1],
          transaction_date: normalizeDate(cells[2]),
          transaction_code: cells[3].toUpperCase(),
          owner_type: cells[4],
          security_type: cells[5],
          shares: cells[6],
          price: cells[7],
          transaction_value: cells[8],
          shares_owned_after: cells[9],
        })}`);
      });
    });
    return lines.join("\n");
  }

  function equityResearchTableText(url) {
    const targets = [
      [/seekingalpha\.com\/symbol\/[^/]+\/options/i, "seeking_alpha", "options_chain"],
      [/zacks\.com\/stock\/quote\/[^/]+\/options-chain/i, "zacks", "options_chain"],
      [/zacks\.com\/stock\/quote\/[^/]+\/greeks-montage/i, "zacks", "greeks_montage"],
      [/zacks\.com\/stock\/research\/[^/]+\/insider-transactions/i, "zacks", "insider_transactions"],
      [/investing\.com\/(?:equities|etfs)\/[^/?#]+-options/i, "investing_pro", "options_chain"],
    ];
    const target = targets.find(([pattern]) => pattern.test(url || ""));
    if (!target || typeof document.querySelectorAll !== "function") {
      return "";
    }
    const [, provider, dataType] = target;
    const lines = [];
    const seen = new Set();
    Array.from(document.querySelectorAll("table, [role='table'], [role='grid']") || []).slice(0, 30).forEach((table) => {
      const headers = Array.from(table.querySelectorAll("thead th, thead td, [role='columnheader']") || [])
        .map((cell) => readableElementText(cell).replace(/\s+/g, " ").trim())
        .filter(Boolean);
      const headerText = headers.join(" ");
      const relevant = dataType === "insider_transactions"
        ? /(?:Filer|Insider).*?(?:Tran|Transaction).*?(?:Shares|Owner)/i.test(headerText)
        : dataType === "greeks_montage"
          ? /Strike/i.test(headerText) && /Delta/i.test(headerText) && /(?:Gamma|Implied|Imp Vol)/i.test(headerText)
          : /Strike/i.test(headerText) && /(?:Bid|Ask|Last|Price)/i.test(headerText) && /(?:Volume|Open Int|Vol)/i.test(headerText);
      if (!relevant) {
        return;
      }
      const rows = Array.from(table.querySelectorAll("tbody tr, [role='row']") || []).slice(0, 250)
        .map((row) => Array.from(row.querySelectorAll("th, td, [role='cell'], [role='gridcell']") || [])
          .map((cell) => readableElementText(cell).replace(/\s+/g, " ").trim()))
        .filter((cells) => cells.length >= 3 && cells.some(Boolean))
        .filter((cells) => JSON.stringify(cells) !== JSON.stringify(headers));
      if (!rows.length) {
        return;
      }
      const signature = JSON.stringify([headers, rows.slice(0, 3)]);
      if (seen.has(signature)) {
        return;
      }
      seen.add(signature);
      lines.push(`EQUITY_RESEARCH_TABLE ${JSON.stringify({ provider, data_type: dataType, headers, rows })}`);
    });
    if (!lines.length) {
      const bodyText = readableElementText(document.body).replace(/\s+/g, " ").trim();
      const unavailable = bodyText.match(/(?:no options available|options are not available|no option data|no insider transactions|no data available)/i);
      if (unavailable) {
        lines.push(`EQUITY_PAGE_UNAVAILABLE ${JSON.stringify({ provider, data_type: dataType, reason: unavailable[0] })}`);
      } else {
        lines.push(`EQUITY_TABLE_MISSING ${JSON.stringify({ provider, data_type: dataType, reason: "No qualifying data table rendered" })}`);
      }
    }
    return lines.join("\n");
  }

  const selectors = ["article", "main", "[role='main']", "body"];
  let text = "";
  for (const selector of selectors) {
    const element = document.querySelector(selector);
    const candidate = readableElementText(element);
    if (candidate.length > text.length) {
      text = candidate;
    }
  }
  const dataText = sourceDataText(window.location.href);
  if (dataText) {
    text = `${dataText}\n${text}`.trim();
  }
  const statementText = seekingAlphaResearchDomText(window.location.href);
  if (statementText) {
    text = `${statementText}\n${text}`.trim();
  }
  const zacksDomText = zacksDomRatingText(window.location.href);
  if (zacksDomText) {
    text = `${zacksDomText}\n${text}`.trim();
  }
  const investingSearchText = investingSearchResultText(window.location.href);
  if (investingSearchText) {
    text = `${investingSearchText}\n${text}`.trim();
  }
  const newsListingText = equityNewsListingText(window.location.href);
  if (newsListingText) {
    text = `${newsListingText}\n${text}`.trim();
  }
  const insiderTransactionsText = zacksInsiderTransactionsText(window.location.href);
  if (insiderTransactionsText) {
    text = `${insiderTransactionsText}\n${text}`.trim();
  }
  const researchTableText = equityResearchTableText(window.location.href);
  if (researchTableText) {
    text = `${researchTableText}\n${text}`.trim();
  }
  text = enrichSourceRatingText(window.location.href, text);
  return {
    final_url: window.location.href,
    title: document.title || null,
    extracted_text: text,
    http_status: 200,
  };
}

function isSeekingAlphaResearchPage(url) {
  return /https?:\/\/(www\.)?seekingalpha\.com\/symbol\/[^/]+\/(?:valuation|growth|profitability|momentum|earnings|peers|income-statement|cash-flow-statement)/i.test(url || "");
}

function isDynamicResearchTablePage(url) {
  return (
    /seekingalpha\.com\/symbol\/[^/]+\/options/i.test(url || "") ||
    /zacks\.com\/stock\/(?:quote\/[^/]+\/(?:options-chain|greeks-montage)|research\/[^/]+\/insider-transactions)/i.test(url || "") ||
    /investing\.com\/(?:equities|etfs)\/[^/?#]+-options/i.test(url || "")
  );
}

async function waitForTabComplete(tabId) {
  for (let i = 0; i < 40; i += 1) {
    const tab = await chrome.tabs.get(tabId);
    if (tab.status === "complete") {
      return;
    }
    await sleep(500);
  }
}

async function completeTask(payload) {
  await apiFetch("/api/browser-tasks/complete", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
}

async function extractArticleFromTab(tabId) {
  let article = {};
  const initialTab = await chrome.tabs.get(tabId);
  await prepareTabForExtraction(tabId, initialTab.url || "");
  for (let attempt = 0; attempt < EXTRACTION_ATTEMPTS; attempt += 1) {
    if (attempt > 0) {
      await prepareTabForExtraction(tabId, article.final_url || "");
    }
    const [result] = await chrome.scripting.executeScript({
      target: { tabId },
      func: extractArticleText,
      world: "MAIN",
    });
    article = result?.result || {};
    if (hasUsefulExtractedText(article)) {
      return article;
    }
    if (attempt < EXTRACTION_ATTEMPTS - 1) {
      await sleep(EXTRACTION_RETRY_MS);
    }
  }
  return article;
}

async function prepareTabForExtraction(tabId, url) {
  if (
    !/https?:\/\/(www\.)?seekingalpha\.com\/symbol\/[^/]+\/ratings/i.test(url || "") &&
    !isSeekingAlphaResearchPage(url) &&
    !isDynamicResearchTablePage(url)
  ) {
    return;
  }
  await chrome.scripting.executeScript({
    target: { tabId },
    func: async () => {
      const actionPattern = /^(Annual|Expand All|Show More|Load More|View More)$/i;
      Array.from(document.querySelectorAll("button, [role='button']") || []).forEach((element) => {
        const label = String(element.innerText || element.textContent || "").trim();
        if (actionPattern.test(label) && element.getAttribute("aria-expanded") !== "true") {
          element.click();
        }
      });
      const positions = [
        Math.floor(document.body.scrollHeight * 0.35),
        Math.floor(document.body.scrollHeight * 0.7),
        document.body.scrollHeight,
      ];
      for (const position of positions) {
        window.scrollTo(0, position);
        await new Promise((resolve) => setTimeout(resolve, 700));
      }
      Array.from(document.querySelectorAll("[style*='overflow'], [class*='scroll' i]") || []).slice(0, 30).forEach((element) => {
        if (element.scrollHeight > element.clientHeight) {
          element.scrollTop = element.scrollHeight;
        }
        if (element.scrollWidth > element.clientWidth) {
          element.scrollLeft = element.scrollWidth;
        }
      });
      window.scrollTo(0, document.body.scrollHeight);
    },
  });
  await sleep(EXTRACTION_RETRY_MS);
}

function hasUsefulExtractedText(article) {
  const text = String(article?.extracted_text || "");
  if (!text) {
    return false;
  }
  const url = String(article?.final_url || "");
  if (/https?:\/\/(www\.)?investing\.com\/search\//i.test(url)) {
    return /^INVESTING_RESULT\s+.+\|\s+\/(?:equities|etfs)\//im.test(text);
  }
  if (/\/income-statement/i.test(url)) {
    return /(?:TTM|Fiscal Year).*?(?:Total Revenues|Revenue)/is.test(text);
  }
  if (/\/cash-flow-statement/i.test(url)) {
    return /(?:TTM|Fiscal Year).*?(?:Cash from Operations|Operating Cash Flow|Capital Expenditure)/is.test(text);
  }
  if (/\/(?:valuation|growth|profitability|momentum)(?:\/|$)/i.test(url)) {
    return /Sector Relative Grade/i.test(text);
  }
  if (/\/earnings\/(?:estimates|revisions)/i.test(url)) {
    return /Annual Estimates (?:Summary|Revisions)/i.test(text);
  }
  if (/\/peers\/comparison/i.test(url)) {
    return /(?:Company Name|Market Cap).*?(?:Valuation|Growth|Profitability)/is.test(text);
  }
  if (isDynamicResearchTablePage(url)) {
    return /^(?:EQUITY_RESEARCH_TABLE|EQUITY_INSIDER_TXN|EQUITY_PAGE_UNAVAILABLE)\s+/m.test(text);
  }
  if (!/https?:\/\/(www\.)?seekingalpha\.com\/symbol\/[^/]+\/ratings/i.test(url)) {
    return true;
  }
  if (/\/ratings\/quant-ratings/i.test(url) && /QUANT RATING HISTORY/.test(text) && !/\d{2}\/\d{2}\/\d{4}\s+[\d.,]+/.test(text)) {
    return false;   // history table not rendered yet: retry instead of reading a half-loaded page
  }
  if (/\/ratings\/sell-side-ratings/i.test(url)) {
    return /(?:Average\s+)?Price Target\s*\$?[0-9]+(?:\.[0-9]+)?/i.test(text);
  }
  return (
    /SA_DATA[^\n]*(?:quantRating|currentQuantRating|authorsRating|authorRatings|sellSideRating|sellSideRatings|wallStreetRating|priceTarget)/i.test(text) ||
    /SA Quant Rating\s+(Strong Buy|Buy|Hold|Sell|Strong Sell|Neutral|Outperform|Underperform)/i.test(text) ||
    /SA Analysts Rating\s+(Strong Buy|Buy|Hold|Sell|Strong Sell|Neutral|Outperform|Underperform)/i.test(text) ||
    /Wall Street Rating\s+(Strong Buy|Buy|Hold|Sell|Strong Sell|Neutral|Outperform|Underperform)/i.test(text) ||
    /(?:Average\s+)?Price Target\s*\$?[0-9]+(?:\.[0-9]+)?/i.test(text)
  );
}


// Agency Holdings Keeper: capture the Seeking Alpha Excel export in memory (runs in the page, MAIN world).
// SA builds the file in the browser; we catch the Blob when the page creates it and suppress the real download.
async function captureSaExport() {
  let captured = null;
  const origCreate = URL.createObjectURL;
  const origClick = HTMLAnchorElement.prototype.click;
  try {
    URL.createObjectURL = function (blob) {
      if (blob instanceof Blob) captured = blob;
      return origCreate.apply(this, arguments);
    };
    HTMLAnchorElement.prototype.click = function () {
      if (this.download && captured) return;
      return origClick.apply(this, arguments);
    };
    let button = null;
    for (let i = 0; i < 40 && !button; i += 1) {
      button = Array.from(document.querySelectorAll("button")).find((b) => /^Download( as Excel)?$/i.test(b.textContent.trim()));
      if (!button) await new Promise((r) => setTimeout(r, 500));
    }
    if (!button) return { error: "Download button not found (logged out?)" };
    button.click();
    for (let i = 0; i < 80 && !captured; i += 1) await new Promise((r) => setTimeout(r, 250));
    if (!captured) return { error: "Export file was not produced" };
    const b64 = await new Promise((resolve, reject) => {
      const reader = new FileReader();
      reader.onload = () => resolve(String(reader.result).split(",")[1] || "");
      reader.onerror = () => reject(reader.error);
      reader.readAsDataURL(captured);
    });
    return { b64, size: captured.size };
  } finally {
    URL.createObjectURL = origCreate;
    HTMLAnchorElement.prototype.click = origClick;
  }
}

async function runSaExportTask(task, tab) {
  const [result] = await chrome.scripting.executeScript({
    target: { tabId: tab.id },
    func: captureSaExport,
    world: "MAIN",
  });
  const out = result?.result || {};
  await completeTask({
    task_id: task.task_id,
    status: out.b64 ? "success" : "failed",
    final_url: tab.url || task.url,
    title: "sa_export",
    extracted_text: out.b64 || null,
    http_status: 200,
    error: out.b64 ? null : out.error || "SA export capture failed",
  });
}

async function runTask(task) {
  let tab;
  try {
    const window = await chrome.windows.getLastFocused();
    tab = await chrome.tabs.create({
      url: task.url,
      active: true,
      windowId: window?.id,
    });
    await waitForTabComplete(tab.id);
    await sleep(PAGE_SETTLE_MS);
    if (task.kind === "sa_export") {
      await runSaExportTask(task, tab);
      return;
    }
    const article = await extractArticleFromTab(tab.id);
    await completeTask({
      task_id: task.task_id,
      status: article.extracted_text ? "success" : "failed",
      final_url: article.final_url || tab.url || task.url,
      title: article.title || tab.title || null,
      extracted_text: article.extracted_text || null,
      http_status: article.http_status || 200,
      error: article.extracted_text ? null : "No visible article text extracted",
    });
  } catch (error) {
    await completeTask({
      task_id: task.task_id,
      status: "failed",
      final_url: tab?.url || task.url,
      title: tab?.title || null,
      extracted_text: null,
      http_status: null,
      error: error.message,
    });
  } finally {
    if (tab?.id) {
      try {
        await chrome.tabs.remove(tab.id);
      } catch {
        // The user may have closed the tab manually.
      }
    }
  }
}

async function poll() {
  if (pollInFlight) {
    return;
  }
  if (pollTimer !== null) {
    clearTimeout(pollTimer);
    pollTimer = null;
  }
  pollInFlight = true;
  try {
    const payload = await apiFetch("/api/browser-tasks/next");
    if (payload.status === "task") {
      await runTask(payload);
    }
  } catch {
    // The local app may be stopped; retry on the next interval.
  } finally {
    pollInFlight = false;
    pollTimer = setTimeout(poll, POLL_MS);
  }
}

if (chrome.alarms && typeof chrome.alarms.create === "function" && chrome.alarms.onAlarm) {
  chrome.alarms.create(WAKE_ALARM, { periodInMinutes: 0.5 });
  chrome.alarms.onAlarm.addListener((alarm) => {
    if (alarm.name === WAKE_ALARM) {
      poll();
    }
  });
}

poll();
