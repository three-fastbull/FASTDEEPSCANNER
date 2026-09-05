(() => {
  const marketNames = { ALL: "ทุกตลาด", US: "สหรัฐ", CN: "จีนแผ่นดินใหญ่", HK: "ฮ่องกง", TH: "ไทย" };
  const fallbackMarkets = { SP500: "US", NASDAQ100: "US", SP400: "US", CSI300: "CN", CHINA50: "CN", HSI: "HK", HSTECH: "HK", SET50: "TH", SET100: "TH", MAI: "TH", SET_SAMPLE: "TH" };
  const pairs = [["marketSelect", "universeSelect"], ["hallMarket", "hallUniverse"]];
  const summary = document.getElementById("universeCoverageSummary");
  const body = document.getElementById("universeCoverageBody");
  const note = document.getElementById("universeCoverageNote");
  const number = new Intl.NumberFormat("th-TH");
  let data = null;
  let pending = null;

  function selection(marketId = "marketSelect", groupId = "universeSelect") {
    const group = document.getElementById(groupId)?.value || "ALL";
    const market = document.getElementById(marketId)?.value || "ALL";
    if (!data) return null;
    if (group !== "ALL") return data.groups.find((item) => item.id === group) || null;
    return market === "ALL" ? data.totals : data.markets.find((item) => item.id === market);
  }

  function renderSummary() {
    const selected = selection();
    if (!summary || !selected) return;
    summary.replaceChildren();
    const group = document.getElementById("universeSelect").value;
    const market = document.getElementById("marketSelect").value;
    const title = document.createElement("strong");
    title.textContent = group === "ALL" ? marketNames[market] : data.groups.find((item) => item.id === group)?.label || group;
    summary.append(title);
    const facts = [
      ["รายชื่อ", selected.registered, null],
      ["มีราคา", selected.price_available, selected.registered],
      ["มีงบ", selected.financial_cached, selected.registered],
      ["งบรายปีครบ 5 ปี", selected.annual_5y, selected.registered],
    ];
    const selectedMarket = group === "ALL" ? market : data.groups.find((item) => item.id === group)?.market;
    if (selectedMarket === "US") {
      facts.push(["งบครบ 5 ปี + Q1-Q4", selected.financial_complete, selected.registered]);
    } else if (selectedMarket === "ALL") {
      const us = data.markets.find((item) => item.id === "US");
      if (us) facts.push(["งบสหรัฐครบ 5 ปี + Q1-Q4", us.financial_complete, us.registered]);
    }
    for (const [label, count, total] of facts) {
      const item = document.createElement("span");
      item.textContent = `${label} ${number.format(count)}${total === null ? " ตัว" : `/${number.format(total)}`}`;
      if (total !== null && count < total) item.className = "coverage-pending";
      summary.append(item);
    }
    if (selected.price_missing || selected.price_stale) {
      const warning = document.createElement("small");
      warning.textContent = `ยังไม่มีราคา ${selected.price_missing} ตัว · ผู้ให้บริการยังไม่มีแท่ง ${data.expected_eod_date} อีก ${selected.price_stale} ตัว`;
      warning.className = "coverage-warning";
      summary.append(warning);
    }
    if (!["US", "ALL"].includes(selectedMarket)) {
      const reportingNote = document.createElement("small");
      reportingNote.textContent = "ไตรมาสแสดงตามรอบที่ตลาดนั้นประกาศ ไม่สร้าง Q1-Q4 ที่ไม่มีการรายงาน";
      summary.append(reportingNote);
    }
  }

  function renderDetails() {
    if (!body) return;
    body.replaceChildren();
    for (const group of data.groups) {
      const row = document.createElement("tr");
      const strictQuarterCoverage = group.market === "US" ? group.financial_complete : "ตามงวดที่เผยแพร่";
      for (const value of [group.label, group.registered, group.price_available, group.price_fresh, group.financial_cached, group.annual_5y, strictQuarterCoverage]) {
        const cell = document.createElement("td");
        cell.textContent = typeof value === "number" ? number.format(value) : value;
        row.append(cell);
      }
      const sourceCell = document.createElement("td");
      const source = group.source;
      const link = document.createElement(source.url?.startsWith("https://") ? "a" : "span");
      link.textContent = source.provider === "Existing local list" ? "รายชื่อเดิมที่ติดตาม" : source.provider;
      if (link.tagName === "A") {
        link.href = source.url;
        link.target = "_blank";
        link.rel = "noopener noreferrer";
      }
      sourceCell.append(link);
      const date = document.createElement("small");
      const basis = source.basis === "ETF holdings proxy" ? "หุ้นที่ ETF ดัชนีถือ" : source.basis === "Official index constituents" ? "ผู้จัดทำดัชนี" : "ยังไม่ตรวจสมาชิกใหม่";
      date.textContent = `${source.as_of || "ไม่ระบุวันที่"} · ${basis}${["error", "stale"].includes(source.state) ? " · รออัปเดต" : ""}`;
      sourceCell.append(date);
      row.append(sourceCell);
      body.append(row);
    }
    note.textContent = `นับหลักทรัพย์ไม่ซ้ำใน ALL; หุ้นหนึ่งตัวอาจอยู่หลายดัชนี และ A/H share เป็นคนละหลักทรัพย์ · ราคาถึงวันตรวจ ${data.expected_eod_date} (เกณฑ์วันทำการ ไม่รวมปฏิทินวันหยุดแต่ละตลาด) · Q1-Q4 ครบ 5 ปีเป็นเกณฑ์เข้มสำหรับงบสหรัฐ ส่วนตลาดอื่นแสดงตามงวดที่ประกาศจริง · งบตรวจล่าสุด ${data.financial_audited_at ? new Date(data.financial_audited_at).toLocaleString("th-TH") : "ยังไม่ตรวจ"} · รายชื่อ ETF เป็นตัวแทนดัชนี ไม่ใช่ไฟล์สมาชิกทางการ; China 50 และ mai เป็นชุดเดิมที่ติดตาม ไม่ใช่ทั้งตลาด`;
  }

  function populate() {
    for (const [marketId, groupId] of pairs) {
      const market = document.getElementById(marketId);
      const group = document.getElementById(groupId);
      if (!market || !group) continue;
      const currentMarket = market.value;
      const currentGroup = group.value;
      market.replaceChildren(new Option(`${marketNames.ALL} (${number.format(data.totals.registered)})`, "ALL"));
      for (const item of data.markets) market.add(new Option(`${marketNames[item.id]} (${number.format(item.registered)})`, item.id));
      group.replaceChildren(new Option("ทุกกลุ่ม", "ALL"));
      for (const item of data.groups) group.add(new Option(`${item.label} (${number.format(item.registered)})`, item.id));
      market.value = currentMarket;
      group.value = data.groups.some((item) => item.id === currentGroup) ? currentGroup : "ALL";
    }
    renderSummary();
    renderDetails();
  }

  async function refresh() {
    if (pending) return pending;
    pending = (async () => {
      try {
        const response = await fetch("/api/universe", { cache: "no-store" });
        if (!response.ok) throw new Error("Universe unavailable");
        const payload = await response.json();
        if (!payload.groups || !payload.totals) throw new Error("Restart FastDeep to load the updated server");
        data = payload;
        populate();
      } catch (error) {
        if (!data && summary) summary.textContent = "ยังตรวจความครบไม่ได้ กรุณาเปิด FastDeep ใหม่จากทางลัดเวอร์ชันล่าสุด";
      } finally {
        pending = null;
      }
      return data;
    })();
    return pending;
  }

  for (const [marketId, groupId] of pairs) {
    const market = document.getElementById(marketId);
    const group = document.getElementById(groupId);
    if (!market || !group) continue;
    const groupMarket = () => data?.groups.find((item) => item.id === group.value)?.market || fallbackMarkets[group.value];
    market.addEventListener("change", () => {
      if (market.value !== "ALL" && groupMarket() && groupMarket() !== "ALL" && groupMarket() !== market.value) group.value = "ALL";
      renderSummary();
    });
    group.addEventListener("change", () => {
      if (groupMarket() && groupMarket() !== "ALL") market.value = groupMarket();
      renderSummary();
    });
  }
  window.fastDeepUniverse = { refresh, selection, renderSummary };
  window.fastDeepUniverse.ready = refresh();
})();
