import datetime
import io
import json
import os
import re
import ssl
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET

import pandas as pd
import streamlit as st

# ---------------------------------------------------------------------------
# 1. 套件載入與環境防呆
# ---------------------------------------------------------------------------
try:
    from bs4 import BeautifulSoup
except ImportError:
    st.error(
        "❌ 系統缺少 'bs4' 套件！請在終端機執行：pip install beautifulsoup4"
    )
    st.stop()

try:
    import openpyxl
except ImportError:
    st.error(
        "❌ 系統缺少 'openpyxl' 套件（匯出 Excel 必備）！請在終端機執行：pip install openpyxl"
    )
    st.stop()

try:
    from google import genai
    from google.genai import types
except ImportError:
    genai = None

# 全域 SSL context，避免爬取特定網站時因憑證過期/異常而報錯崩潰
ssl_context = ssl.create_default_context()
ssl_context.check_hostname = False
ssl_context.verify_mode = ssl.CERT_NONE

# 頁面配置
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

# 每日 API 計算器重置
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
        font-size: 1.1rem !important;
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
    '<div class="main-header">📰 彰化家扶中心輿情自動檢索與報表生成系統</div>',
    unsafe_allow_html=True,
)
st.markdown(
    '<div class="sub-header">支援全網頁小報無 API 本地深度檢索、雙重關聯過濾與記者精準辨識</div>',
    unsafe_allow_html=True,
)

st.markdown(
    """
<div class="warning-bar">
    <p class="warning-text">※此系統為個人自主開發，請勿用做非法行為😈</p>
    <p class="warning-text">※已強化全網小報抓取與記者識別演算法，結合雙重檢核精準過濾無關新聞🌏</p>
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
# 4. 關鍵演算法：HTTP Fetch + 雙重過濾 + 強化記者 Sensor + 防爆設計
# ---------------------------------------------------------------------------

def fetch_article_text(url):
    """嘗試取得新聞網頁的前段內文，用於精準抓取記者姓名與過濾雜訊 (含防爆機制)"""
    if not url or not isinstance(url, str) or not url.startswith(("http://", "https://")):
        return ""

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    }
    try:
        req = urllib.request.Request(url, headers=headers)
        # 加入 context=ssl_context 防護憑證問題
        with urllib.request.urlopen(req, timeout=4, context=ssl_context) as response:
            # 防爆：動態檢查編碼，若無預設為 utf-8
            charset = response.headers.get_param("charset") or "utf-8"
            try:
                html = response.read().decode(charset, errors="replace")
            except Exception:
                html = response.read().decode("utf-8", errors="ignore")

            soup = BeautifulSoup(html, "html.parser")

            # 移除腳本與樣式標籤
            for script in soup(["script", "style", "noscript", "header", "footer"]):
                script.extract()

            text = soup.get_text(separator=" ")
            # 清理空白字元並截取前 1000 字（記者名字通常在開頭）
            clean_text = re.sub(r"\s+", " ", text).strip()
            return clean_text[:1000]
    except Exception:
        # 防爆：避免連線逾時、404、403、SSL錯誤中斷整個流程
        return ""


def extract_reporter_sensor(text):
    """高精度記者姓名辨識 Sensor：支援更多常見媒體記者格式 (含防爆機制)"""
    if not text or not isinstance(text, str):
        return "編輯部"

    patterns = [
        # 專利格式：〔記者張小明／彰化報導〕, 記者張小明／彰化報導
        r"〔?記者\s*([\u4e00-\u9fa5]{2,4})\s*[\/／]\s*[\u4e00-\u9fa5]+報導〕?",
        # 格式：記者張小明報導
        r"記者\s*([\u4e00-\u9fa5]{2,4})\s*報導",
        # 格式：文／張小明、圖／張小明
        r"(?:文|圖|攝影)\s*[\/／]\s*([\u4e00-\u9fa5]{2,4})",
        # 格式：張小明／彰化報導
        r"([\u4e00-\u9fa5]{2,4})\s*[\/／]\s*(?:彰化|地方|即時|綜合|專題)+報導",
        # 格式：(記者張小明)
        r"[\(（]記者\s*([\u4e00-\u9fa5]{2,4})[\)）]",
        # 通用兜底
        r"(?<!新聞)(?<!家扶)(?<!媒體)(?<!即時)(?<!中心)\b([\u4e00-\u9fa5]{2,4})\s*報導",
    ]

    exclude_words = [
        "新聞", "家扶", "中心", "本報", "綜合", "特別", "即時", 
        "彰化", "地方", "責任", "編輯", "專題", "社會", "生活", "焦點"
    ]

    for pattern in patterns:
        try:
            match = re.search(pattern, text)
            if match:
                name = match.group(1).strip()
                if name not in exclude_words:
                    return name
        except Exception:
            continue
    return "編輯部"


def parse_media_from_url_or_title(title, url, source_elem_text=None):
    """本地辨識媒體名稱 (含防爆機制)"""
    title = str(title) if title else ""
    url = str(url) if url else ""

    if source_elem_text and str(source_elem_text).strip():
        return str(source_elem_text).strip()

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
        "pchome.com.tw": "PChome新聞",
        "yam.com": "蕃新聞",
        "yahoo.com": "Yahoo奇摩新聞",
    }

    for domain, name in domain_map.items():
        if domain in url:
            return name

    try:
        match = re.search(r"[\-\|｜\_]\s*([^\-\|｜\_]+)$", title)
        if match:
            possible_media = match.group(1).strip()
            if len(possible_media) <= 12:
                return possible_media
    except Exception:
        pass

    return "地方網路新聞"


def fetch_google_news_rss(org, keyword):
    """
    ⚡ 高穩定 Google News RSS 檢索引擎 (含完整 SSL 與 XML 解析防爆)
    """
    search_query = f'"{org}" "{keyword}"'
    encoded_query = urllib.parse.quote(search_query)
    rss_url = f"https://news.google.com/rss/search?q={encoded_query}&hl=zh-TW&gl=TW&ceid=TW:zh-Hant"

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    }

    results = []
    try:
        req = urllib.request.Request(rss_url, headers=headers)
        with urllib.request.urlopen(req, timeout=10, context=ssl_context) as response:
            xml_data = response.read()

        root = ET.fromstring(xml_data)
        for item in root.findall(".//item"):
            try:
                title = item.find("title").text if item.find("title") is not None else ""
                link = item.find("link").text if item.find("link") is not None else ""
                pub_date = item.find("pubDate").text if item.find("pubDate") is not None else ""
                source_elem = item.find("source")
                source_text = source_elem.text if source_elem is not None else ""

                if title and link:
                    media_name = parse_media_from_url_or_title(title, link, source_text)
                    results.append(
                        {
                            "title": title,
                            "url": link,
                            "media_name": media_name,
                            "date": pub_date,
                        }
                    )
            except Exception:
                continue # 單一項目解析失敗自動跳過
    except Exception as e:
        st.error(f"⚠️ RSS 檢索出現異常：{e}")

    return results


def lookup_media_type(media_name, media_map):
    """對照媒體類別 (含防爆機制)"""
    if not media_name:
        return "非三大報全國性"
    
    m_name = str(media_name).strip()
    if m_name in media_map:
        return media_map[m_name]
    for k, v in media_map.items():
        if k in m_name or m_name in k:
            return v
    return "非三大報全國性"


def clean_title_local(title):
    """標題清理 (去除網站後綴，含防爆)"""
    if not title:
        return ""
    try:
        cleaned = re.sub(r"\s*[\-\|｜\_]\s*.*$", "", str(title))
        return cleaned.strip()
    except Exception:
        return str(title)


def run_news_pipeline(
    office, staff_name, org, keyword, year, media_map, GEMINI_API_KEY
):
    # 記錄檢索歷史
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

    # 1. 啟動 RSS 穩定爬蟲
    with st.spinner(
        f"🕷️ 正在搜羅全網新聞報導（含地方新聞與全網新聞網）『{org} {keyword}』..."
    ):
        raw_results = fetch_google_news_rss(org, keyword)

    if not raw_results:
        st.error("❌ 未抓取到相關網頁，請嘗試更換關鍵字。")
        return []

    # 2. 初始化 Gemini Client
    client = None
    if genai and GEMINI_API_KEY:
        try:
            client = genai.Client(api_key=GEMINI_API_KEY)
        except Exception as e:
            st.sidebar.warning(f"⚠️ Gemini 初始化失敗：{e}")

    results = []
    
    # 建立動態文字與進度條佔位元件
    progress_text_slot = st.empty()
    progress_bar = st.progress(0)
    total_items = len(raw_results)

    for i, item in enumerate(raw_results):
        percent = int((i + 1) / total_items * 100)
        
        progress_text_slot.markdown(f"✈️ **新聞深度解析與相關性過濾中：{percent}%**")
        progress_bar.progress(percent)

        cleaned_title = clean_title_local(item["title"])
        media_name = item["media_name"]
        m_type = lookup_media_type(media_name, media_map)

        # 🚀 關鍵改進：抓取新聞網頁開頭內文，用於雙重判定與記者提取
        article_snippet = fetch_article_text(item["url"])
        combined_text = f"標題：{item['title']}\n內文開頭：{article_snippet}"

        # 1. 本地硬過濾：若標題與內文完全不含關鍵字或機構，判定為無關新聞並跳過
        if (org not in cleaned_title and org not in article_snippet) and \
           (keyword not in cleaned_title and keyword not in article_snippet):
            continue

        # 2. 本地 Sensor 優先從內文+標題抓取記者姓名
        reporter_name = extract_reporter_sensor(combined_text)

        # 3. 若 Gemini 可用，進行 AI 語意過濾、淨化與記者確認
        is_relevant = True
        if client:
            try:
                st.session_state["api_count_today"] += 1
                prompt = f"""
                你是一個新聞輿情分析助手。請分析以下新聞內容：
                {combined_text}

                請執行以下任務：
                1. 判斷這篇新聞是否與「{org}」以及「{keyword}」高度相關？ (填寫 true 或 false)
                2. 清理新聞標題，移除媒體名稱、頻道或來源後綴。
                3. 辨識記者/撰稿人姓名 (若無則填 '{reporter_name}')。

                傳回 JSON 格式：
                {{"is_relevant": true, "title": "純標題", "reporter": "記者姓名"}}
                """
                response = client.models.generate_content(
                    model="gemini-2.5-flash",
                    contents=prompt,
                    config=types.GenerateContentConfig(
                        response_mime_type="application/json"
                    ),
                )
                
                # 防爆：清理可能包含 Markdown 標記的字串
                raw_json = response.text.strip()
                if raw_json.startswith("```json"):
                    raw_json = raw_json.split("```json")[1].split("```")[0].strip()
                elif raw_json.startswith("```"):
                    raw_json = raw_json.split("```")[1].split("```")[0].strip()

                parsed = json.loads(raw_json)
                is_relevant = parsed.get("is_relevant", True)
                cleaned_title = parsed.get("title", cleaned_title)
                reporter_name = parsed.get("reporter", reporter_name)
            except Exception:
                # 防爆：API 異常、解析失敗時自動降級為本地邏輯，保留項目
                pass

        # 若 AI 認定為無關新聞，則予以剔除
        if not is_relevant:
            continue

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

    # 任務完成後清空進度條區塊
    progress_text_slot.empty()
    progress_bar.empty()
    return results


# ---------------------------------------------------------------------------
# 5. UI 與主流程控制
# ---------------------------------------------------------------------------
if sidebar_option == "🔍 檢索系統":
    st.markdown('<div class="search-card">', unsafe_allow_html=True)
    st.subheader("🔍 新聞輿情搜尋條件")

    col1, col2 = st.columns(2)
    with col1:
        office = st.selectbox(
            "🏢 選擇服務處：",
            ["全部", "和美兒童館", "員林服務處", "彰化服務處", "二林服務處", "田中服務處"],
        )
        org = st.text_input(
            "🏛️ 搜尋機構名稱：", value="", placeholder="e.g. 彰化家扶"
        )
        year_input = st.text_input(
            "📅 目標年份：", value="", placeholder=f"e.g. {datetime.date.today().year}"
        )

    with col2:
        staff_name = st.text_input("👤 主責同工姓名：", value="", placeholder="e.g. 張小明")
        keyword = st.text_input(
            "🔑 搜尋新聞關鍵字：", value="", placeholder="e.g. 課輔班、相見歡、寒冬送暖"
        )

    search_button = st.button("🚀 開始全網檢索與生成報表", use_container_width=True)
    st.markdown("</div>", unsafe_allow_html=True)

    if search_button:
        target_org = org.strip() if org.strip() else "彰化家扶"
        
        # 年份防爆轉型
        try:
            clean_year_str = re.sub(r"\D", "", year_input.strip())
            year = int(clean_year_str) if clean_year_str else datetime.date.today().year
        except ValueError:
            year = datetime.date.today().year

        if not keyword.strip() or not staff_name.strip():
            st.warning("⚠️ 請完整填寫「搜尋新聞關鍵字」與「主責同工姓名」！")
        else:
            final_data = run_news_pipeline(
                office, staff_name.strip(), target_org, keyword.strip(), year, media_type_map, api_key
            )

            if final_data:
                df_result = pd.DataFrame(final_data)
                df_result = df_result.drop_duplicates(subset=["新聞連結"])

                st.success(f"🎉 成功捕捉到 {len(df_result)} 筆高品質新聞！")
                st.balloons()
                st.dataframe(df_result, use_container_width=True)

                # Excel 生成防爆
                try:
                    output = io.BytesIO()
                    with pd.ExcelWriter(output, engine="openpyxl") as writer:
                        df_result.to_excel(
                            writer, index=False, sheet_name="新聞輿情統計"
                        )

                    st.download_button(
                        label="📥 下載輿情統計 Excel 報表",
                        data=output.getvalue(),
                        file_name=f"{target_org}_{keyword}_精準輿情報表.xlsx",
                        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                        use_container_width=True,
                    )
                except Exception as e:
                    st.error(f"❌ 產出 Excel 報表時發生錯誤：{e}")
            else:
                st.info("ℹ️ 未能找到符合條件的新聞，或過濾後無相關結果。建議擴大關鍵字範圍試試！")

elif sidebar_option == "💡 系統簡介":
    st.subheader("💡 全網小報檢索系統特點")
    st.markdown(
        """
    **彰化家扶中心輿情自動檢索與報表生成系統**旨在幫助同工快速彙整網路媒體報導。

    * **即時檢索**：自動爬取 Google 最新相關新聞與網頁報導。
    * **雙重過濾**：自動採集網頁內文與標題，透過嚴格比對機制排除同名或無關的新聞雜訊。
    * **記者深度辨識**：突破標題限制，深入網頁前 1000 字開頭提取專利格式與記者署名。
    * **AI 結構化整理**：運用 Gemini AI 自動識別新聞標題、發布年份、記者姓名、對照媒體分類並進行資料淨化。
    * **一鍵報表**：自動產出包含服務處、主責查詢同工、媒體分類與超連結的標準化 Excel 檔案。
    """
    )

elif sidebar_option == "📌 系統須知":
    st.subheader("📌 系統須知與使用規範")
    st.success("※本版本已升級「內文深度探針」與「語意雙重過濾」，大幅減少無關新聞並提高記者命中率📈")
    st.warning(
        """
    1. **遵守使用規範**：本系統僅供彰化家扶內部輿情檢索使用，嚴禁用於商業爬蟲或任何非法用途！
    2. **雙保險機制**：系統優先採用 Gemini Flash 模型與內文爬取；若網頁被防爬蟲阻擋或 API 額滿，會自動降級至本地 Sensor 演算法！
    3. **資料準確性**：報表匯出後，請人工進行二次核對，確保無遺漏。
    4. **非網路新聞補充**：紙本報紙、電視新聞等露出請務必人工補充。
    """
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

            try:
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
            except Exception as e:
                st.error(f"❌ 產出管理員報表失敗：{e}")
        else:
            st.info("目前尚無搜尋歷史紀錄。")
    elif admin_key:
        st.error("❌ 金鑰錯誤！")
