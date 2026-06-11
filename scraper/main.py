#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
硬件价格追踪爬虫
从 ZOL 产品详情页提取：产品名、参考价、京东价、天猫价
写入 data/YYYY-MM.json，追加历史记录
"""

import json
import os
import sys
import time
from datetime import datetime, timezone, timedelta

import requests
from bs4 import BeautifulSoup

# -------- 配置 --------
BASE_URL = "https://detail.zol.com.cn"
PRODUCTS_FILE = os.path.join(os.path.dirname(os.path.dirname(__file__)), "products.json")
DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data")
REQUEST_DELAY = 3           # 请求间隔（秒）
REQUEST_TIMEOUT = 20         # 请求超时（秒）
REQUEST_RETRY = 2            # 失败重试次数
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
)

# -------- 工具函数 --------
def tz_beijing() -> timezone:
    return timezone(timedelta(hours=8))


def today_str() -> str:
    """返回北京时间今天的日期字符串 YYYY-MM-DD"""
    return datetime.now(tz_beijing()).strftime("%Y-%m-%d")


def month_key() -> str:
    """返回年月 YYYY-MM，用于文件分片"""
    return datetime.now(tz_beijing()).strftime("%Y-%m")


def load_products() -> list:
    """加载关注产品列表"""
    with open(PRODUCTS_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def fetch_page(url: str) -> str | None:
    """获取页面 HTML 内容（GBK 解码），支持重试"""
    for attempt in range(REQUEST_RETRY + 1):
        try:
            resp = requests.get(
                url,
                headers={"User-Agent": USER_AGENT},
                timeout=REQUEST_TIMEOUT,
            )
            resp.raise_for_status()
            resp.encoding = "gbk"
            return resp.text
        except Exception as e:
            if attempt < REQUEST_RETRY:
                print(f"  [!] 重试 {attempt+1}/{REQUEST_RETRY}: {e}")
                time.sleep(REQUEST_DELAY * 2)
            else:
                print(f"  [X] 请求失败: {e}")
                return None


def extract_price(soup: BeautifulSoup, selector: str) -> int | None:
    """从 soup 中用 CSS 选择器提取价格，返回整数（分）或 None"""
    el = soup.select_one(selector)
    if not el:
        return None
    raw = el.text.strip()
    if not raw:
        return None
    # 清洗：去掉 ¥ ￥ 等符号，去掉逗号，保留数字和小数点
    cleaned = ""
    for ch in raw:
        if ch.isdigit() or ch == ".":
            cleaned += ch
    if not cleaned:
        return None
    try:
        price_float = float(cleaned)
        # 如果价格小于 10，可能是元；大于 10 万的可能是奇怪的数字（如天猫显示"2.12万"）
        return int(round(price_float))
    except ValueError:
        return None


def scrape_product(product: dict) -> dict:
    """爬取单个产品的价格数据"""
    zol_path = product["zol_url"]
    url = BASE_URL + zol_path
    product_id = product["id"]
    product_name = product["name"]

    print(f"  [{product_id}] {product_name}")
    print(f"    请求: {url}")

    html = fetch_page(url)
    if not html:
        return {"id": product_id, "name": product_name, "zol_price": None,
                "jd_price": None, "tmall_price": None, "error": True}

    soup = BeautifulSoup(html, "lxml")

    # 提取产品名（以页面实际标题为准）
    h1 = soup.select_one("h1")
    actual_name = h1.text.strip() if h1 else product_name

    # 提取参考价
    ref_sign = soup.select_one(".price__reference .price-sign")
    ref_type = soup.select_one(".price__reference .price-type")
    ref_price = None
    if ref_sign and ref_type:
        ref_raw = ref_sign.text + ref_type.text
        ref_price = extract_price_from_text(ref_raw)

    # 提取京东价
    jd_price = extract_price(soup, ".b2c-jd .m-price")

    # 提取天猫价
    tmall_price = extract_price(soup, ".b2c-tmall .m-price")

    print(f"    参考价: {ref_price}, 京东价: {jd_price}, 天猫价: {tmall_price}")

    return {
        "id": product_id,
        "name": actual_name,
        "zol_price": ref_price,
        "jd_price": jd_price,
        "tmall_price": tmall_price,
        "error": False,
    }


def extract_price_from_text(raw: str) -> int | None:
    """从任意文本中提取价格"""
    cleaned = ""
    for ch in raw:
        if ch.isdigit() or ch == ".":
            cleaned += ch
    if not cleaned:
        return None
    try:
        return int(round(float(cleaned)))
    except ValueError:
        return None


def load_existing_data(month: str) -> dict:
    """加载已有数据文件"""
    filepath = os.path.join(DATA_DIR, f"{month}.json")
    if os.path.exists(filepath):
        with open(filepath, "r", encoding="utf-8") as f:
            return json.load(f)
    return {"month": month, "records": []}


def save_data(month: str, data: dict):
    """保存数据文件"""
    filepath = os.path.join(DATA_DIR, f"{month}.json")
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def main():
    print("=" * 55)
    print("  硬件价格追踪爬虫  —  ", datetime.now(tz_beijing()).strftime("%Y-%m-%d %H:%M"))
    print("=" * 55)

    products = load_products()
    print(f"  共 {len(products)} 款产品\n")

    today = today_str()
    month = month_key()

    # 加载现有本月数据
    data = load_existing_data(month)

    # 检查今天是否已经爬过
    for rec in data["records"]:
        if rec.get("date") == today:
            print(f"[!] 今天 ({today}) 已有数据，跳过爬取")
            print(f"    如需强制更新请删除 data/{month}.json 中的当天记录")
            return

    # 逐款爬取
    prices = []
    success_count = 0
    for i, product in enumerate(products):
        result = scrape_product(product)
        prices.append(result)
        if not result.get("error"):
            success_count += 1
        # 请求间延迟（最后一个不需要）
        if i < len(products) - 1:
            time.sleep(REQUEST_DELAY)

    # 写入 JSON
    record = {
        "date": today,
        "prices": prices,
    }
    data["records"].append(record)
    save_data(month, data)

    print(f"\n{'='*55}")
    print(f"  完成: {success_count}/{len(products)} 款产品采集成功")
    print(f"  数据: data/{month}.json  (总记录 {len(data['records'])} 条)")
    print(f"{'='*55}")

    # 生成简单文本摘要
    print(f"\n  {today} 行情速览\n  {'-'*30}")
    for p in prices:
        if p.get("error"):
            print(f"  {p['name']:40s} [采集失败]")
        else:
            jd = f"JD:{p['jd_price']}" if p['jd_price'] else "JD:-"
            zol = f"ZOL:{p['zol_price']}" if p['zol_price'] else "ZOL:-"
            print(f"  {p['name'][:35]:35s}  {zol:>10}  {jd:>10}")


if __name__ == "__main__":
    main()
