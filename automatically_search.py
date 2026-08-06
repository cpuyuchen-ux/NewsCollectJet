import datetime
import io
import json
import os
import re
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET

import pandas as pd
import streamlit as st
from google import genai
from google.genai import types

# ---------------------------------------------------------------------------
# 1. 頁面配置與自訂 CSS 樣式
# ---------------------------------------------------------------------------
st.set_page_config(
    page_title="彰化家扶輿情自動檢索與報表生成系統",
    page_icon="📰",
    layout="wide",
    initial_sidebar_state="expanded",
)

# 初始化 Session State
if "api_count_today" not in st.session_state:
    st.session_state["api_count_today"] = 0
if "last_api_date" not in st.session_state:
    st.session_state["last_api_date"] = datetime.date.today()
if "search_history" not in st.session_state:
    st.session_state["search_history"] = []

if st.session_state["last_api_date"] != datetime.date.today():
    st.session_state["api_count_today"] = 0
    st.session_state["last_api_date"] = datetime.date.today()

# 注入自訂 CSS
st.markdown(
    """
<style>
    .main { background-color: #f8f9fa; }
    .main-header { font-size: 2.2rem; font-weight: 700; color: #1F2937; margin-bottom: 0.2rem; }
    .sub-header { color: #6B7280; font-size: 1.0rem; margin-bottom: 0.8rem; }
    .warning-bar {
        background-color: #FEF2F2;
        border-left: 5px solid #EF4444;
        padding: 0.75rem 1rem;
        border-radius: 6px;
        margin-bottom: 1.5rem;
    }
    .warning-text { color: #DC2626; font-weight: 700; font-size: 0.95rem; margin: 0; }
    .search-card {
        background-color: #ffffff;
        padding: 1.5rem;
        border-radius: 12px;
        box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.05);
        border: 1px solid #E5E7EB;
        margin-bottom: 1.5rem;
    }
    [data-testid="stSidebar"] { background-color: #f1f5f9; border-right: 1px solid #E2E8F0; }
    div.stButton > button:first-child {
        background: linear-gradient(90deg, #2563EB, #1D4ED8);
        color: white; border: none; padding: 0.6rem 1.2rem;
        font-weight: 600; border-radius: 8px; transition: all 0.3s ease;
    }
    div.stButton > button:first-child:hover {
        background: linear-gradient(90deg, #1D4ED8, #1E40AF);
        transform: translateY(-1px);
    }
</style>
""",
    unsafe_allow_html=True,
)

# ---------------------------------------------------------------------------
# 2. 標題與警示橫幅區塊
# ---------------------------------------------------------------------------
st.markdown(
    '<div class="main-header">📰 彰化家扶中心輿情自動檢索與報表生成系統</div>',
    unsafe_allow_html=True,
)
st.markdown(
    '<div class="sub-header">自動整合 Google News 即時新聞，並透過 Gemini AI 自動進行年份對齊與格式化</div>',
    unsafe_allow_html=True,
)

st.markdown(
    """
<div class="warning-bar">
    <p class="warning-text">※此系統為個人自主開發，請勿用做非法行為😈</p>
    <p class="warning-text">※檢索資料庫為「彰化家扶」常見出報媒體，資料庫將不定期更新👀</p>
    <p class="warning-text">※此系統供同工免費使用，惟開發者仍保有此系統所有權🔧</p>
</div>
""",
    unsafe_allow_html=True,
)

# ---------------------------------------------------------------------------
# 3. 側邊欄與資料庫讀取
# ---------------------------------------------------------------------------
st.sidebar.title("⚙️ 系統核心設定")

sidebar_option = st.sidebar.selectbox(
    "請選擇功能模組：",
    ["主控台 / 檢索系統", "系統簡介", "系統須知", "系統管理員"],
)

api_key = st.secrets.get("GEMINI_API_KEY", "")
if not api_key:
    api_key = st.sidebar.text_input(
        "🔑 輸入 Gemini API Key:",
        type="password",
        help="請輸入您的 Gemini API Key",
    )

st.sidebar.markdown("---")

db_file_path = "database.csv"
media_type_map = {}

if os.path.exists(db_file_path):
    try:
        db_df = pd.read_csv(db_file_path, encoding="utf-8").dropna(how="all")
        st.sidebar.success("✅ database.csv 已連線")
        if len(db_df.columns) >= 2:
            media_col = db_df.columns[0]
            type_col = db_df.columns[1]
            media_type_map = dict(
                zip(
                    db_df[media_col].astype(str).str.strip(),
                    db_df[type_col].astype(str).str.strip(),
                )
            )
    except Exception as e:
        st.sidebar.error(f"❌ 讀取 database.csv 失敗: {e}")

# ---------------------------------------------------------------------------
# 4. 輔助函式定義
# ---------------------------------------------------------------------------
def render_airplane_progress(percent, text=""):
    return f"""
    <div style="width: 100%; margin-top: 10px; margin-bottom: 20px;">
        <div style="font-size: 0.9rem; font-weight: 600; color: #374151; margin-bottom: 5px;">{text}</div>
        <div style="width: 100%; background-color: #E5E7EB; border-radius: 10px; height: 24px; position: relative; overflow: hidden;">
            <div style="width: {percent}%; background: linear-gradient(90deg, #3B82F6, #1D4ED8); height: 100%; transition: width 0.4s ease; display: flex; align-items: center; justify-content: flex-end; padding-right: 5px;">
                <span style="font-size: 14px;">🛫</span>
            </div>
        </div>
        <div style="text-align: right; font-size: 0.85rem; font-weight: 700; color: #2563EB; margin-top: 3px;">🛫 {percent}%</div>
    </div>
    """


def lookup_media_type(media_name, media_map):
    """本地字典模糊與精準比對媒體類別"""
    m_name = str(media_name).strip()
    if m_name in media_map:
        return media_map[m_name]
    for k, v in media_map.items():
        if k in m_name or m_name in k:
            return v
    return "非三大報全國性"


def clean_title_local(title):
    """本地純 Python 標題清理演算法"""
    cleaned = re.sub(r"\s*-\s*.*$", "", title)
    cleaned = re.sub(r"｜.*$", "", cleaned)
    cleaned = re.sub(r"\|.*$", "", cleaned)
    return cleaned.strip()


def run_news_pipeline(
    office, staff_name, org, keyword, year, media_map, GEMINI_API_KEY
):
    st.session_state["search_history"].append(
        {
            "檢索時間": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "服務處": office,
            "同工姓名": staff_name,
            "機構": org,
            "關鍵字": keyword,
            "目標年份": year,
        }
    )

    search_query = f"{org} {keyword}"
    encoded_query = urllib.parse.quote(search_query)
    rss_url = f"https://news.google.com/rss/search?q={encoded_query}&hl=zh-TW&gl=TW&ceid=TW:zh-Hant"

    raw_results = []
    with st.spinner(f"📡 正在經由 Google News 檢索『{search_query}』新聞報導..."):
        try:
            req = urllib.request.Request(
                rss_url,
                headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"},
            )
            with urllib.request.urlopen(req, timeout=10) as response:
                xml_data = response.read()
            root = ET.fromstring(xml_data)
            for item in root.findall(".//item"):
                title = item.find("title").text if item.find("title") is not None else ""
                link = item.find("link").text if item.find("link") is not None else ""
                pub_date = item.find("pubDate").text if item.find("pubDate") is not None else ""
                source = item.find("source").text if item.find("source") is not None else "新聞媒體"

                raw_results.append(
                    {
                        "title": title,
                        "url": link,
                        "date": pub_date,
                        "media_name": source,
                    }
                )
        except Exception as e:
            st.error(f"❌ Google News 檢索異常：{e}")
            return []

    if not raw_results:
        return []

    results = []
    client = genai.Client(api_key=GEMINI_API_KEY) if GEMINI_API_KEY else None

    batch_size = 5
    batches = [
        raw_results[i : i + batch_size]
        for i in range(0, len(raw_results), batch_size)
    ]

    progress_placeholder = st.empty()
    progress_placeholder.markdown(
        render_airplane_progress(0, f"🤖 開始處理新聞資料 (共 {len(batches)} 批次)..."),
        unsafe_allow_html=True,
    )

    for idx, batch in enumerate(batches, start=1):
        if client:
            batch_payload = [
                {
                    "id": i,
                    "title": item["title"],
                    "date": item["date"],
                    "media_name": item["media_name"],
                }
                for i, item in enumerate(batch)
            ]

            prompt = f"""
            新聞列表：{json.dumps(batch_payload, ensure_ascii=False)}
            條件：發布年份須為 {year}，標題或內容需包含 {org} 或 {keyword}。
            請去除標題末端媒體名稱後綴（如「 - 自由時報」），並提取記者姓名 (若無填 '編輯部')。
            傳回 JSON 格式：
            {{"articles": [{{"id": 0, "media_name": "媒體名稱", "title": "純標題", "reporter": "記者姓名"}}]}}
            """

            try:
                st.session_state["api_count_today"] += 1
                response = client.models.generate_content(
                    model="gemini-1.5-flash",
                    contents=prompt,
                    config=types.GenerateContentConfig(
                        response_mime_type="application/json"
                    ),
                )
                res_data = json.loads(response.text)
                for parsed in res_data.get("articles", []):
                    item_orig = batch[parsed["id"]]
                    m_type = lookup_media_type(parsed.get("media_name", item_orig["media_name"]), media_map)
                    results.append(
                        {
                            "服務處": office,
                            "查報同工": staff_name,
                            "媒體名稱": parsed.get("media_name", item_orig["media_name"]),
                            "媒體類別": m_type,
                            "新聞標題": parsed.get("title", clean_title_local(item_orig["title"])),
                            "記者": parsed.get("reporter", "編輯部"),
                            "新聞連結": item_orig["url"],
                        }
                    )
            except Exception:
                # 若 AI 發生異常則切換為本地清理備援
                for item in batch:
                    m_type = lookup_media_type(item["media_name"], media_map)
                    results.append(
                        {
                            "服務處": office,
                            "查報同工": staff_name,
                            "媒體名稱": item["media_name"],
                            "媒體類別": m_type,
                            "新聞標題": clean_title_local(item["title"]),
                            "記者": "編輯部",
                            "新聞連結": item["url"],
                        }
                    )
        else:
            # 無 API Key 時使用純本地清洗
            for item in batch:
                m_type = lookup_media_type(item["media_name"], media_map)
                results.append(
                    {
                        "服務處": office,
                        "查報同工": staff_name,
                        "媒體名稱": item["media_name"],
                        "媒體類別": m_type,
                        "新聞標題": clean_title_local(item["title"]),
                        "記者": "編輯部",
                        "新聞連結": item["url"],
                    }
                )

        # 進度條更新
        progress_pct = int((idx / len(batches)) * 100)
        progress_placeholder.markdown(
            render_airplane_progress(
                progress_pct, f"🤖 正在處理第 {idx}/{len(batches)} 批次新聞..."
            ),
            unsafe_allow_html=True,
        )

    progress_placeholder.empty()
    return results


# ---------------------------------------------------------------------------
# 5. 功能模組切換 (包含主控台與搜尋介面)
# ---------------------------------------------------------------------------
if sidebar_option == "主控台 / 檢索系統":
    st.markdown('<div class="search-card">', unsafe_allow_html=True)
    st.subheader("🔍 新聞輿情搜尋條件")

    col1, col2 = st.columns(2)
    with col1:
        office = st.selectbox(
            "🏢 選擇服務處：",
            ["和美", "員林", "彰化", "鹿港", "二林", "田中"],
        )
        org = st.text_input("🏛️ 搜尋機構名稱：", value="彰化家扶")
        year = st.number_input(
            "📅 目標年份：", min_value=2000, max_value=2030, value=datetime.date.today().year
        )

    with col2:
        staff_name = st.text_input("👤 主責同工姓名：", value="張同工")
        keyword = st.text_input("🔑 搜尋新聞關鍵字：", value="園遊會")

    search_button = st.button("🚀 開始檢索與生成報表", use_container_width=True)
    st.markdown("</div>", unsafe_allow_html=True)

    if search_button:
        if not keyword.strip():
            st.warning("⚠️ 請輸入搜尋關鍵字！")
        else:
            final_data = run_news_pipeline(
                office, staff_name, org, keyword, year, media_type_map, api_key
            )

            if final_data:
                df_result = pd.DataFrame(final_data)
                st.success(f"🎉 成功找到 {len(df_result)} 筆符合條件的新聞！")
                st.dataframe(df_result, use_container_width=True)

                output = io.BytesIO()
                with pd.ExcelWriter(output, engine="openpyxl") as writer:
                    df_result.to_excel(
                        writer, index=False, sheet_name="新聞輿情統計"
                    )

                st.download_button(
                    label="📥 下載輿情統計 Excel 報表",
                    data=output.getvalue(),
                    file_name=f"{org}_{keyword}_{year}_輿情報表.xlsx",
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    use_container_width=True,
                )
            else:
                st.info("ℹ️ 未檢索到相關新聞，請嘗試更換關鍵字或年份。")

elif sidebar_option == "系統簡介":
    st.subheader("💡 系統簡介")
    st.markdown(
        """
    **彰化家扶中心輿情自動檢索與報表生成系統** 旨在幫助同工快速彙整網路媒體報導。

    * **即時檢索**：自動爬取 Google News 最新相關新聞。
    * **AI 結構化整理**：運用 Gemini AI 自動識別新聞標題、發布年份、記者姓名、對照媒體分類並進行資料淨化。
    * **一鍵報表**：自動產出包含服務處、主責查詢同工、媒體分類與超連結的標準化 Excel 檔案。
    * **本地備用演算法**：若未填寫 API Key 或遇到網路請求限制，系統會切換至本地文字清理演算法。
    """
    )

elif sidebar_option == "系統須知":
    st.subheader("📌 系統須知與使用規範")
    st.warning(
        """
    1. **遵守使用規範**：本系統僅供彰化家扶內部輿情檢索使用，嚴禁用於商業爬蟲或非法用途。
    2. **資料準確性**：AI 自動解析結果僅供參考，匯出報表後建議人工進行二次核對。
    3. **中心 PDF 檔留存**：報表生成後，請將每一篇報導儲存成 PDF 檔放置於中心查報資料夾備查。
    4. **非網路新聞補充**：本系統僅能抓取網路電子新聞，紙本報紙、廣播、電視新聞等露出請人工補充。
    """
    )

elif sidebar_option == "系統管理員":
    st.subheader("🔐 系統管理員後台")
    admin_key = st.text_input("🔑 請輸入管理員金鑰：", type="password")

    if admin_key == "Automation_initiator114077":
        st.success("🔓 驗證成功，歡迎進入管理員後台！")
        col_m1, col_m2, col_m3 = st.columns(3)
        col_m1.metric("📅 今日日期", str(st.session_state["last_api_date"]))
        col_m2.metric(
            "📡 今日 API 請求次數", f"{st.session_state['api_count_today']} 次"
        )
        col_m3.metric(
            "🔍 累積檢索次數", f"{len(st.session_state['search_history'])} 筆"
        )

        st.markdown("---")
        st.subheader("📊 檢索歷史紀錄與統計")

        if st.session_state["search_history"]:
            history_df = pd.DataFrame(st.session_state["search_history"])
            st.dataframe(history_df, use_container_width=True)

            history_output = io.BytesIO()
            with pd.ExcelWriter(history_output, engine="openpyxl") as writer:
                history_df.to_excel(
                    writer, index=False, sheet_name="系統使用統計"
                )

            st.download_button(
                label="📥 匯出管理員統計報表 (Excel)",
                data=history_output.getvalue(),
                file_name=f"系統使用紀錄_{datetime.date.today()}.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                use_container_width=True,
            )
        else:
            st.info("目前尚無搜尋歷史紀錄。")

    elif admin_key:
        st.error("❌ 金鑰錯誤，無法存取管理員後台！")
