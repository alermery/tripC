/** 与 FastAPI HTTPException detail 等结构兼容的展示文案 */
function formatApiDetail(detail) {
  if (detail == null || detail === "") return "";
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail)) {
    return detail
      .map((item) =>
        item && typeof item === "object" && item.msg != null ? item.msg : JSON.stringify(item)
      )
      .join("；");
  }
  if (typeof detail === "object") {
    return detail.message || detail.msg || JSON.stringify(detail);
  }
  return String(detail);
}

async function readResponseJson(response) {
  const text = await response.text();
  if (!text.trim()) return {};
  try {
    return JSON.parse(text);
  } catch {
    return { _notJson: true, _raw: text.slice(0, 240) };
  }
}
