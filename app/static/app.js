/* 健康助手：提示、删除确认、总览图表 */
(function () {
  const params = new URLSearchParams(location.search);
  if (params.get("msg")) toast(params.get("msg"));
  document.querySelectorAll("form.js-del").forEach((f) => {
    f.addEventListener("submit", (e) => {
      if (!confirm("确定删除？")) e.preventDefault();
    });
  });
})();

function toast(text) {
  const el = document.getElementById("toast");
  if (!el) return;
  el.textContent = text;
  el.classList.add("show");
  setTimeout(() => el.classList.remove("show"), 3200);
}

function bootHealth() {
  const data = JSON.parse(document.getElementById("chart-data").textContent);
  const C = { sys: "#dc2626", dia: "#2563eb", wt: "#059669" };

  if ((data.bp || []).length) {
    const t = data.bp.map((d) => d.t);
    mk("chart-bp", {
      tooltip: { trigger: "axis" },
      legend: { data: ["收缩压", "舒张压", "心率"], top: 0 },
      grid: { left: 8, right: 8, top: 32, bottom: 0, containLabel: true },
      xAxis: { type: "category", data: t },
      yAxis: [
        { type: "value", min: 40, max: 200 },
        { type: "value", name: "心率", splitLine: { show: false } },
      ],
      series: [
        { name: "收缩压", type: "line", data: data.bp.map((d) => d.sys), itemStyle: { color: C.sys }, symbolSize: 5, markLine: { silent: true, symbol: "none", lineStyle: { color: "#dc2626", type: "dashed" }, data: [{ yAxis: 140, label: { formatter: "高压线140" } }, { yAxis: 90, label: { formatter: "低压线90" } }] } },
        { name: "舒张压", type: "line", data: data.bp.map((d) => d.dia), itemStyle: { color: C.dia }, symbolSize: 5 },
        { name: "心率", type: "line", yAxisIndex: 1, data: data.bp.map((d) => d.hr || null), itemStyle: { color: "#9ca3af" }, symbolSize: 4, lineStyle: { type: "dotted" } },
      ],
    });
  } else noData("chart-bp", "暂无血压记录");

  if ((data.wt || []).length) {
    mk("chart-wt", {
      tooltip: { trigger: "axis", valueFormatter: (v) => v + " kg" },
      grid: { left: 8, right: 12, top: 20, bottom: 0, containLabel: true },
      xAxis: { type: "category", data: data.wt.map((d) => d.t) },
      yAxis: { type: "value", scale: true },
      series: [{ type: "line", data: data.wt.map((d) => d.kg), itemStyle: { color: C.wt }, areaStyle: { opacity: 0.08 }, smooth: true, symbolSize: 5 }],
    });
  } else noData("chart-wt", "暂无体重记录");
}

function mk(id, option) {
  const el = document.getElementById(id);
  if (!el || typeof echarts === "undefined") return;
  const c = echarts.init(el);
  c.setOption(option);
  window.addEventListener("resize", () => c.resize());
}

function noData(id, text) {
  const el = document.getElementById(id);
  if (el) el.innerHTML = `<div class="empty" style="height:100%;display:flex;align-items:center;justify-content:center">${text}</div>`;
}
