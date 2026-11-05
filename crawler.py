"""
工程线索采集智能浏览器助手
功能：自动翻页、提取项目信息、识别电话、过滤无效内容
"""
import asyncio
import json
import csv
import re
import argparse
from pathlib import Path
from playwright.async_api import async_playwright


# 项目关键词（所有可能需要备用电源的项目）
KEYWORDS = [
    "煤矿", "矿山", "厂房", "产业园", "泵站", "水厂", "数据中心",
    "储能", "隧道", "污水处理", "风电", "光伏", "变电站", "管廊",
    "小区", "住宅", "楼盘", "房地产", "商业", "酒店", "学校", "医院",
    "大厦", "广场", "工业", "建筑", "新建"
]

# 无效内容黑名单（和备用电源完全无关的）
BLACKLIST = [
    "绿化", "亮化", "景观", "维修", "装修", "设计", "监理", "勘察",
    "停工", "停产", "竣工", "完工", "拆除", "烂尾", "路灯", "路面修补"
]


def extract_phone(text: str) -> list:
    """从文本里提取电话号码"""
    phones = re.findall(r'1[3-9]\d{9}', text)
    landline = re.findall(r'0\d{2,3}-?\d{7,8}', text)
    return list(set(phones + landline))


def filter_valid_project(title: str) -> bool:
    """判断是不是有效项目"""
    # 命中黑名单直接无效
    for kw in BLACKLIST:
        if kw in title:
            return False
    # 命中关键词才算有效
    for kw in KEYWORDS:
        if kw in title:
            return True
    return False


async def browse_page(url: str, max_pages: int = 5, interval: int = 4, output: str = "output.json"):
    """自动翻页采集列表"""
    results = []

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False)
        context = await browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
        )
        page = await context.new_page()

        print(f"[INFO] 打开: {url}")
        try:
            await page.goto(url, wait_until="networkidle", timeout=30000)
        except Exception as e:
            print(f"[ERROR] 加载失败: {e}")
            await browser.close()
            return

        current_url = page.url
        page_num = 1

        while page_num <= max_pages:
            print(f"\n[INFO] 第 {page_num} 页: {current_url}")
            await asyncio.sleep(2)

            page_text = await page.inner_text("body")
            links = await page.eval_on_selector_all(
                "a",
                "els => els.map(e => ({text: e.innerText.trim(), href: e.href}))"
            )
            # 过滤有效链接
            valid_links = []
            for l in links:
                if not l["text"] or len(l["text"]) < 6:
                    continue
                if "javascript:" in l["href"]:
                    continue
                if filter_valid_project(l["text"]):
                    phones = extract_phone(l["text"] + page_text[:2000])
                    valid_links.append({
                        "title": l["text"],
                        "url": l["href"],
                        "phones": phones
                    })

            print(f"[INFO] 找到 {len(valid_links)} 个有效项目链接")
            results.append({
                "page": page_num,
                "url": current_url,
                "valid_projects": valid_links,
                "page_text_snippet": page_text[:2000]
            })

            # 检测验证码
            if "验证码" in page_text or "captcha" in page_text.lower():
                print("\n[!] 遇到验证码，请手动完成后按回车继续...")
                input()

            # 翻页
            if page_num < max_pages:
                print(f"[INFO] 等待 {interval} 秒翻页...")
                await asyncio.sleep(interval)

                # 更多翻页按钮识别方式
                next_selectors = [
                    "text=下一页", "text=下页", "text=>", ".next", "#next",
                    "a:has-text('下一页')", "li.next a", "a.next-page"
                ]
                clicked = False
                for sel in next_selectors:
                    try:
                        btn = await page.query_selector(sel)
                        if btn and await btn.is_visible():
                            await btn.click()
                            await page.wait_for_load_state("networkidle", timeout=15000)
                            current_url = page.url
                            clicked = True
                            print(f"[INFO] 翻页成功: {current_url}")
                            break
                    except:
                        continue
                if not clicked:
                    print("[WARN] 没找到下一页，停止")
                    break
            page_num += 1

        # 保存结果
        out = Path(output)
        out.parent.mkdir(parents=True, exist_ok=True)
        with open(out, "w", encoding="utf-8") as f:
            json.dump(results, f, ensure_ascii=False, indent=2)
        print(f"\n[INFO] 完成！结果保存到: {out.resolve()}")
        print(f"[INFO] 共 {len(results)} 页，{sum(len(p['valid_projects']) for p in results)} 个有效项目")

        input("\n按回车关闭浏览器...")
        await browser.close()


async def open_detail(url: str, output: str = "detail.txt"):
    """打开详情页提取全文"""
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False)
        page = await browser.new_page()
        print(f"[INFO] 打开详情: {url}")
        try:
            await page.goto(url, wait_until="networkidle", timeout=30000)
            await asyncio.sleep(2)
            text = await page.inner_text("body")
            phones = extract_phone(text)

            out = Path(output)
            out.parent.mkdir(parents=True, exist_ok=True)
            with open(out, "w", encoding="utf-8") as f:
                f.write(f"URL: {url}\n")
                f.write(f"标题: {await page.title()}\n")
                f.write(f"提取到的电话: {phones}\n")
                f.write("="*60 + "\n")
                f.write(text)
            print(f"[INFO] 详情保存到: {out.resolve()}")
        except Exception as e:
            print(f"[ERROR] 失败: {e}")
        input("按回车关闭...")
        await browser.close()


def export_csv(json_file: str, csv_file: str):
    """导出CSV"""
    with open(json_file, "r", encoding="utf-8") as f:
        data = json.load(f)

    rows = []
    for page in data:
        for proj in page["valid_projects"]:
            rows.append({
                "项目名称": proj["title"],
                "项目地址": "【无公示信息】",
                "业主单位": "【无公示信息】",
                "总包单位": "【无公示信息】",
                "联系电话": ", ".join(proj["phones"]) if proj["phones"] else "【无公示信息】",
                "来源链接": proj["url"]
            })

    with open(csv_file, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["项目名称", "项目地址", "业主单位", "总包单位", "联系电话", "来源链接"])
        writer.writeheader()
        writer.writerows(rows)
    print(f"[INFO] CSV导出完成: {csv_file}，共 {len(rows)} 条")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="工程线索采集助手")
    sub = parser.add_subparsers(dest="cmd")

    p1 = sub.add_parser("browse")
    p1.add_argument("--url", required=True)
    p1.add_argument("--max-pages", type=int, default=5)
    p1.add_argument("--interval", type=int, default=4)
    p1.add_argument("--output", default="output.json")

    p2 = sub.add_parser("detail")
    p2.add_argument("--url", required=True)
    p2.add_argument("--output", default="detail.txt")

    p3 = sub.add_parser("export")
    p3.add_argument("--input", required=True)
    p3.add_argument("--output", required=True)

    args = parser.parse_args()
    if args.cmd == "browse":
        asyncio.run(browse_page(args.url, args.max_pages, args.interval, args.output))
    elif args.cmd == "detail":
        asyncio.run(open_detail(args.url, args.output))
    elif args.cmd == "export":
        export_csv(args.input, args.output)
    else:
        parser.print_help()
