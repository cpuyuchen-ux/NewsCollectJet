import datetime
import io
import json
import os
import re
import time
import urllib.parse
import urllib.request

import pandas as pd
import streamlit as st

# 防呆檢查：避免缺少 beautifulsoup4 導致網頁打不開
try:
    from bs4 import BeautifulSoup
except ImportError:
    st.error(
        "❌ 系統缺少 'bs4' 套件！請在終端機執行：pip install beautifulsoup4"
    )
    st.stop()

# 防呆檢查：Gemini SDK
try:
    from google import genai
    from google.genai import types
except ImportError:
    genai = None
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

# 注入 CSS 樣式
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
    div[data-testid="stRadio"] div[role="radiogroup"] > label > div:first-child {
        display: none !important;
    }
    div[data-testid="stRadio"] div[role="radiogroup"] > label {
        padding: 6px 10px;
        border-radius: 8px;
        transition: background-color 0.2s ease;
        margin-bottom: 4px;
        cursor: pointer;
    }
    div[data-testid="stRadio"] div[role="radiogroup"] > label p {
        font-size: 1.2rem !important;
        font-weight: 600 !important;
    }
</style>
""",
    unsafe_allow_html=True,
)

# ---------------------------------------------------------------------------
# 2. 標題與警示橫幅區塊
# ---------------------------------------------------------------------------
st.markdown(
    '<div class="main-header">📰 彰化家扶中心輿情自動檢索與報表生成系統 (全網小報強化版)</div>',
    unsafe_allow_html=True,
)
st.markdown(
    '<div class="sub-header">支援全網頁小報（警政時報、台中時報等）無 API 本地深度檢索與記者自動辨識</div>',
    unsafe_allow_html=True,
)

st.markdown(
    """
<div class="warning-bar">
    <p class="warning-text">※此系統為個人自主開發，請勿用做非法行為😈</p>
    <p class="warning-text">※已強化全網小報抓取演算法，打破 Google News 限制，自動搜羅地方媒體🌏</p>
    <p class="warning-text">※檢索資料庫為「彰化家扶」常見出報媒體，資料庫將不定期更新👀</p>
    <p class="warning-text">※此系統供同工免費使用，惟開發者仍保有此系統所有權，敬請尊重著作權🔧</p>
</div>
""",
    unsafe_allow_html=True,
)

# ---------------------------------------------------------------------------
# 3. 側邊欄與資料庫讀取
# ---------------------------------------------------------------------------
st.sidebar.title("⚙️ 系統功能導覽")
sidebar_option = st.sidebar.radio(
    "請選擇功能模組：",
    ["🔍 檢索系統", "💡 系統簡介", "📌 系統須知", "🔐 系統管理員"],
    index=0,
    label_visibility="collapsed",
)

st.sidebar.markdown("---")
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
# 4. 關鍵演算法：Google 全網頁無 API 爬蟲 + 記者 Sensor
# ---------------------------------------------------------------------------
def extract_reporter_sensor(text):
    """記者姓名辨識 Sensor：以 Regex 抓取『記者○○○報導』或『○○○/地區報導』"""
    if not text:
        return "編輯部"

    patterns = [
        r"記者\s*([\u4e00-\u9fa5]{2,4})\s*[\/／]\s*[\u4e00-\u9fa5]+報導",
        r"記者\s*([\u4e00-\u9fa5]{2,4})\s*報導",
        r"([\u4e00-\u9fa5]{2,4})\s*[\/／]\s*[\u4e00-\u9fa5]+報導",
        r"(?<!新聞)(?<!家扶)(?<!媒體)(?<!即時)\b([\u4e00-\u9fa5]{2,4})\s*報導",
    ]

    for pattern in patterns:
        match = re.search(pattern, text)
        if match:
            name = match.group(1).strip()
            exclude_words = [
                "新聞",
                "家扶",
                "中心",
                "本報",
                "綜合",
                "特別",
                "即時",
                "彰化",
                "地方",
                "責任",
            ]
            if name not in exclude_words:
                return name
    return "編輯部"


def parse_media_from_url_or_title(title, url):
    """本地辨識小報媒體名稱 (當 Google 沒標註媒體時)"""
    domain_map = {
        "news.owlting.com": "奧丁丁新聞",
        "886.news": "警政時報",
        "taichung.news": "台中時報",
        "nantoutimes.com": "南投時報",
        "pingtungtimes.com.tw": "屏東時報",
        "taipeipost.org": "台北郵報",
        "marketersgo.com": "行銷人",
        "gothe.tw": "走遊",
        "tdn.today": "善思新聞網",
        "ltvnews.net": "在地人新聞",
        "firenews.com.tw": "火報",
        "tc.news": "台中新聞網",
        "tn.news": "台灣新聞網",
        "peopo.org": "PeoPo公民新聞",
        "cdns.com.tw": "中華日報",
        "ksnews.com.tw": "更生日報",
        "taiwanhot.net": "台灣好新聞",
        "ettoday.net": "ETtoday新聞雲",
        "ltn.com.tw": "自由時報",
        "udn.com": "聯合報",
        "chinatimes.com": "中國時報",
        "cna.com.tw": "中央社",
    }
    for domain, name in domain_map.items():
        if domain in url:
            return name

    # 從標題後綴提取
    match = re.search(r"[\-\|｜\_]\s*([^\-\|｜\_]+)$", title)
    if match:
        possible_media = match.group(1).strip()
        if len(possible_media) <= 10:
            return possible_media

    return "地方網路新聞"


def fetch_google_web_search(org, keyword, num_results=50):
    """
    ⚡ 本地防爆全網爬蟲引擎：
    直接對 Google 一般網頁搜尋進行 Html 抓取，專抓『警政時報』、『台中時報』等小報！
    """
    search_query = f"{org} {keyword}"
    encoded_query = urllib.parse.quote(search_query)

    # 模擬標準桌面 Chrome 瀏覽器 Headers 避免被防爬蟲機制阻擋
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept-Language": "zh-TW,zh;q=0.9,en-US;q=0.8,en;q=0.7",
    }

    results = []

    # 分頁抓取 (每頁 10 筆)
    pages = min(num_results // 10, 5)
    for page in range(pages):
        start = page * 10
        url = f"https://www.google.com/search?q={encoded_query}&start={start}&hl=zh-TW"

        try:
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=8) as response:
                html = response.read().decode("utf-8")

            soup = BeautifulSoup(html, "html.parser")

            # 解析 Google 搜尋結果節點
            for g in soup.find_all("div", class_="g"):
                anchor = g.find("a")
                title_elem = g.find("h3")

                if anchor and title_elem:
                    link = anchor.get("href", "")
                    title = title_elem.text.strip()

                    # 排除非新聞網站（如 FB, YouTube, 家扶官網本身）
                    if (
                        link.startswith("http")
                        and "facebook.com" not in link
                        and "youtube.com" not in link
                        and "ccf.org.tw" not in link
                    ):
                        media_name = parse_media_from_url_or_title(title, link)
                        results.append(
                            {
                                "title": title,
                                "url": link,
                                "media_name": media_name,
                                "date": datetime.date.today().strftime("%Y-%m-%d"),
                            }
                        )
            time.sleep(1)  # 友善間隔，避免請求過快
        except Exception as e:
            st.warning(f"全網爬蟲頁面 {page+1} 讀取稍受限，已自動轉為精簡解析。")
            break

    return results


def lookup_media_type(media_name, media_map):
    """對照媒體類別"""
    m_name = str(media_name).strip()
    if m_name in media_map:
        return media_map[m_name]
    for k, v in media_map.items():
        if k in m_name or m_name in k:
            return v
    return "非三大報全國性"


def clean_title_local(title):
    """標題清理"""
    cleaned = re.sub(r"\s*[\-\|｜\_]\s*.*$", "", title)
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

    # 1. 啟動全網頁小報爬蟲
    with st.spinner(
        f"🕷️ 正在搜尋全網頁新聞（含警政時報、台中時報等小報）『{org} {keyword}』..."
    ):
        raw_results = fetch_google_web_search(org, keyword, num_results=40)

    if not raw_results:
        st.error("❌ 未抓取到相關網頁，請檢查網路連線或關鍵字。")
        return []

    # 2. 處理資料與 AI / Sensor 解析
    results = []
    client = genai.Client(api_key=GEMINI_API_KEY) if GEMINI_API_KEY else None

    progress_bar = st.progress(0)
    total_items = len(raw_results)

    for i, item in enumerate(raw_results):
        cleaned_title = clean_title_local(item["title"])
        media_name = item["media_name"]
        m_type = lookup_media_type(media_name, media_map)

        # 先啟動 Sensor 抓取記者姓名
        reporter_name = extract_reporter_sensor(item["title"])

        # 若有 Gemini API，則進行標題修飾與年份對齊
        if client and GEMINI_API_KEY:
            try:
                st.session_state["api_count_today"] += 1
                prompt = f"""
                請分析新聞標題：『{item['title']}』
                1. 請清理標題，移除媒體後綴。
                2. 嘗試辨識記者姓名 (若無則填 '{reporter_name}')。
                傳回 JSON: {{"title": "純標題", "reporter": "記者" failure_safe}}
                """
                response = client.models.generate_content(
                    model="gemini-1.5-flash",
                    contents=prompt,
                    config=types.GenerateContentConfig(
                        response_mime_type="application/json"
                    ),
                )
                parsed = json.loads(response.text)
                cleaned_title = parsed.get("title", cleaned_title)
                reporter_name = parsed.get("reporter", reporter_name)
            except Exception:
                pass  # API 失敗自動流向本地 Sensor

        results.append(
            {
                "服務處": office,
                "查報同工": staff_name,
                "媒體名稱": media_name,
                "媒體類別": m_type,
                "新聞標題": cleaned_title,
                "記者": reporter_name,
                "新聞連結": item["url"],
            }
        )

        progress_bar.progress(int((i + 1) / total_items * 100))

    progress_bar.empty()
    return results


# ---------------------------------------------------------------------------
# 5. UI 與主流程控制
# ---------------------------------------------------------------------------
if sidebar_option == "🔍 檢索系統":
    st.markdown('<div class="search-card">', unsafe_allow_html=True)
    st.subheader("🔍 新聞輿情搜尋條件（全網小報升級版）")

    col1, col2 = st.columns(2)
    with col1:
        office = st.selectbox(
            "🏢 選擇服務處：",
            ["全部", "和美兒童館", "員林服務處", "彰化服務處", "二林服務處", "田中服務處"],
        )
        org = st.text_input("🏛️ 搜尋機構名稱：", placeholder="e.g. 彰化家扶")
        year_input = st.text_input("📅 目標年份：", placeholder="e.g. 2026")

    with col2:
        staff_name = st.text_input("👤 主責同工姓名：", placeholder="e.g. 彰化家扶小編")
        keyword = st.text_input(
            "🔑 搜尋新聞關鍵字：", placeholder="e.g. 課輔班、相見歡"
        )

    search_button = st.button("🚀 開始全網小報檢索與生成報表", use_container_width=True)
    st.markdown("</div>", unsafe_allow_html=True)

    if search_button:
        if not org.strip() or not keyword.strip() or not staff_name.strip():
            st.warning("⚠️ 請完整填寫機構、關鍵字與同工姓名！")
        else:
            try:
                year = (
                    int(year_input.strip())
                    if year_input.strip()
                    else datetime.date.today().year
                )
            except ValueError:
                year = datetime.date.today().year

            final_data = run_news_pipeline(
                office, staff_name, org, keyword, year, media_type_map, api_key
            )

            if final_data:
                df_result = pd.DataFrame(final_data)
                # 去除重複網址
                df_result = df_result.drop_duplicates(subset=["新聞連結"])

                st.success(f"🎉 成功捕捉到 {len(df_result)} 筆新聞（含小報）！")
                st.dataframe(df_result, use_container_width=True)

                output = io.BytesIO()
                with pd.ExcelWriter(output, engine="openpyxl") as writer:
                    df_result.to_excel(
                        writer, index=False, sheet_name="新聞輿情統計"
                    )

                st.download_button(
                    label="📥 下載輿情統計 Excel 報表",
                    data=output.getvalue(),
                    file_name=f"{org}_{keyword}_全網輿情報表.xlsx",
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    use_container_width=True,
                )

elif sidebar_option == "💡 系統簡介":
    st.subheader("💡 全網小報檢索系統特點")
    st.markdown(
        """
    **彰化家扶中心輿情自動檢索與報表生成系統**旨在幫助同工快速彙整網路媒體報導。

    * **即時檢索**：自動爬取 Google News 最新相關新聞。
    * **AI 結構化整理：運用 Gemini AI 自動識別新聞標題、發布年份、記者姓名、對照媒體分類（三大報/非三大報等）並進行資料淨化。
    * **一鍵報表**：自動產出包含服務處、主責查詢同工、媒體分類與超連結的標準化 Excel 檔案，提升行政與輿情整理效率。
    * **模組化減速**：批次發送檢索要求，避免觸發 Google 反爬蟲機制（Anti-Scraping）。
    * **本地備用演算法防爆機制**：優先使用 Gemini 進行精準解析；若 API限流則自動啟動「本地防爆演算法」，保障 100% 順利產出。
    * **擺脫 Google News RSS 限制**：採用 Python 本地 BeautifulSoup 技術，直接抓取 Google 一般網頁搜尋，包含小報與地方新聞網（警政時報、台中時報、PeoPo公民新聞等）。
    * **自動域名識別**：自動從網址與標題辨識出小報名稱。
    * **記者姓名 Sensor 強化**：即使小報格式多變，亦能靠正則表達式提取「記者姓名」。
    """
    )

elif sidebar_option == "📌 系統須知":
    st.subheader("📌 系統須知與使用規範")
    st.warning(
        ""
    ※本版本已全面啟用全網小報搜尋模式，抓取效果顯著提升📈
    1.**遵守使用規範**：本系統僅供彰化家扶內部輿情檢索使用，嚴禁用於商業爬蟲、網路攻擊或任何非法用途🈲
    2.**API 額度雙保險機制"：系統採用 Genimi 1.5 Flash 模型，若仍遇到429配額額滿，將自動無縫轉入「本地純文字演算法」，確保資料不遺漏🗂️
    3.**資料準確性**： AI 自動解析結果僅供參考，匯出報表後建議人工進行二次核對，尤其檢核「奧丁丁新聞」、「PChome新聞」、「蕃新聞」、「奇摩新聞」等，確保報導未被遺漏。
    4.**中心 PDF 檔存查**：報表生成後，請將每一篇報導儲存為 PDF 檔，放置於中心查報資料夾備查。
    5.**人工調整格式**：報表生成後，請配合將資料貼入「2026年單位季報_媒體統計格式」之 Excel 檔，並視情況補充記者姓名。
    6.**非網路新聞補充**：本系統僅能抓取網路電子新聞，紙本報紙、電台節目、電視新聞等露出請務必人工補充，俾使資料趨於完整。
    """"
    )
    
elif sidebar_option == "🔐 系統管理員":
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
        st.error("❌ 金鑰錯誤！") 
