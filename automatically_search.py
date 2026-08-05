import io
import json
import os
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
import pandas as pd
import streamlit as st
from google import genai
from google.genai import types

# ---------------------------------------------------------------------------
# 1. 頁面配置與標題
# ---------------------------------------------------------------------------
st.set_page_config(page_title="彰化中心輿情自動檢索系統", page_icon="📰", layout="wide")

st.title("📰 彰化中心輿情自動檢索與報表生成系統")
st.caption("自動經由 Google News RSS 抓取新聞，並運用 Gemini AI 精準篩選年份與格式化")

# ---------------------------------------------------------------------------
# 2. 金鑰與自動載入內部數據庫 (方案 A)
# ---------------------------------------------------------------------------
st.sidebar.header("⚙️ 系統設定")

# 讀取 API Key (優先讀取 Secrets)
api_key = st.secrets.get("GEMINI_API_KEY", "")
if not api_key:
    api_key = st.sidebar.text_input("輸入 Gemini API Key:", type="password")

if not api_key:
    st.warning("⚠️ 請先在 Streamlit Secrets 設定 `GEMINI_API_KEY` 或於左側欄位輸入 API Key 以開始使用。")
    st.stop()

st.sidebar.markdown("---")
st.sidebar.subheader("🗄️ 內部數據庫狀態")

# 自動讀取同目錄下的 Database.csv 檔案
db_file_path = "Database.csv"
db_df = None

if os.path.exists(db_file_path):
    try:
        db_df = pd.read_csv(db_file_path)
        st.sidebar.success(f"✅ 已載入內部數據庫\n(共 {len(db_df)} 筆參考資料)")
    except Exception as e:
        st.sidebar.error(f"❌ 讀取 Database.csv 失敗: {e}")
else:
    st.sidebar.info("ℹ️ 未檢測到 Database.csv (系統將以一般模式搜尋)")

# ---------------------------------------------------------------------------
# 3. 核心搜尋與 AI 分批解析 (強化版重試機制)
# ---------------------------------------------------------------------------
def run_news_pipeline(org, keyword, year, db_df, GEMINI_API_KEY):
    db_context = ""
    if db_df is not None:
        db_context = db_df.to_string(index=False)[:500]

    # A. 組合搜尋關鍵字並進行 URL 編碼
    search_query = f"{org} {keyword}"
    encoded_query = urllib.parse.quote(search_query)
    
    # B. 存取 Google News 台灣區中文 RSS 串流
    rss_url = f"https://news.google.com/rss/search?q={encoded_query}&hl=zh-TW&gl=TW&ceid=TW:zh-Hant"
    
    raw_results = []
    with st.spinner(f"正在經由 Google News 檢索『{search_query}』新聞報導..."):
        try:
            req = urllib.request.Request(
                rss_url, 
                headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'}
            )
            with urllib.request.urlopen(req, timeout=10) as response:
                xml_data = response.read()
                
            root = ET.fromstring(xml_data)
            for item in root.findall('.//item'):
                title = item.find('title').text if item.find('title') is not None else ""
                link = item.find('link').text if item.find('link') is not None else ""
                pub_date = item.find('pubDate').text if item.find('pubDate') is not None else ""
                source = item.find('source').text if item.find('source') is not None else "新聞媒體"
                
                raw_results.append({
                    "title": title,
                    "url": link,
                    "date": pub_date,
                    "media_name": source
                })
        except Exception as e:
            st.error(f"Google News 檢索異常：{e}")
            return []

    if not raw_results:
        return []

    # C. AI 分批解析 (每批 10 筆，降低 Token 消耗)
    results = []
    client = genai.Client(api_key=GEMINI_API_KEY)
    
    batch_size = 10
    batches = [raw_results[i:i + batch_size] for i in range(0, len(raw_results), batch_size)]
    
    progress_bar = st.progress(0, text=f"🤖 Gemini 正在精準篩選 {year} 年份報導並整理結構...")
    
    for idx, batch in enumerate(batches, start=1):
        prompt = f"""
        數據庫參考：{db_context}
        原始新聞：{json.dumps(batch, ensure_ascii=False)}

        請篩選出符合條件的新聞：
        1. 標題或內容包含「{org}」與「{keyword}」。
        2. 發布年份必須為『{year}』年。
        3. 清除標題中的媒體名稱後綴。

        輸出 JSON：
        {{
            "articles": [
                {{
                    "media_name": "媒體名稱",
                    "title": "純標題",
                    "reporter": "記者姓名 (若無填 '編輯部')",
                    "url": "新聞連結"
                }}
            ]
        }}
        """
        
        # 強制重試機制 (最多重試 3 次，間隔 60 秒)
        max_retries = 3
        success = False
        
        for attempt in range(1, max_retries + 1):
            try:
                response = client.models.generate_content(
                    model="gemini-2.0-flash",
                    contents=prompt,
                    config=types.GenerateContentConfig(response_mime_type="application/json")
                )
                res_data = json.loads(response.text)
                results.extend(res_data.get("articles", []))
                success = True
                break
            except Exception as e:
                st.toast(f"⏳ 第 {idx}/{len(batches)} 批次觸發頻率限制，自動等待 60 秒重試 (嘗試 {attempt}/{max_retries})...", icon="⏳")
                time.sleep(60)
        
        if not success:
            st.warning(f"⚠️ 第 {idx} 批次於多次重試後依然失敗，已跳過該批次。")
            
        progress_bar.progress(idx / len(batches))
        time.sleep(5.0)
        
    progress_bar.empty()
    return results

# ---------------------------------------------------------------------------
# 4. 主要 UI 操作介面
# ---------------------------------------------------------------------------
col1, col2, col3 = st.columns(3)
with col1:
    target_org = st.text_input("機構/品牌名稱", value="麗寶樂園")
with col2:
    search_keyword = st.text_input("搜尋關鍵字", value="斷軌")
with col3:
    target_year = st.text_input("指定目標年份 (YYYY)", value="2026")

if st.button("🚀 開始自動化檢索", type="primary", use_container_width=True):
    if not target_org or not search_keyword or not target_year:
        st.error("請完整填寫搜尋條件！")
    else:
        results = run_news_pipeline(target_org, search_keyword, target_year, db_df, api_key)
        
        if not results:
            st.warning(f"未找到符合條件的 {target_year} 年新聞報導 (或因免費 API 額度限制未能順利解析)。")
        else:
            st.success(f"🎉 成功找到 {len(results)} 筆符合條件的 {target_year} 年新聞報導！")
            
            df_display = pd.DataFrame(results)
            df_export = df_display[["media_name", "title", "reporter", "url"]].copy()
            df_export.columns = ["媒體名稱", "新聞標題", "記者", "新聞連結"]
            
            st.dataframe(
                df_export,
                column_config={
                    "新聞連結": st.column_config.LinkColumn("新聞連結")
                },
                use_container_width=True,
                hide_index=True
            )
            
            output = io.BytesIO()
            with pd.ExcelWriter(output, engine='openpyxl') as writer:
                df_export.to_excel(writer, index=False, sheet_name='輿情報導')
                
                worksheet = writer.sheets['輿情報導']
                for row_idx, url in enumerate(df_export['新聞連結'], start=2):
                    cell = worksheet.cell(row=row_idx, column=4)
                    cell.hyperlink = url
                    cell.style = "Hyperlink"
                
                worksheet.column_dimensions['A'].width = 20
                worksheet.column_dimensions['B'].width = 50
                worksheet.column_dimensions['C'].width = 15
                worksheet.column_dimensions['D'].width = 40

            st.download_button(
                label="📥 下載 Excel 輿情報表",
                data=output.getvalue(),
                file_name=f"{target_org}_{search_keyword}_{target_year}_輿情報表.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                use_container_width=True
            )
