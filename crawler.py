"""
工程线索采集浏览器辅助脚本
用途：本地电脑Agent调用，负责打开浏览器、翻页、提取页面文本、保存结果
注意：本脚本只做机械动作，具体字段提取和过滤规则由Agent判断
"""
import asyncio
import json
import csv
import argparse
import time
from pathlib import Path
from playwright.async_api import async_playwright


async def browse_page(url: str, max_pages: int = 3, interval: int = 4, output: str = "output.json"):
    """
    打开目标网页，自动翻页，提取每页文本和链接
    :param url: 目标公告列表页URL
    :param max_pages: 最大翻页数
    :param interval: 每页间隔秒数（防反爬）
    :param output: 输出文件路径
    """
    results = []

    async with async_playwright() as p:
        # 启动有头浏览器，用户能看到操作过程
        browser = await p.chromium.launch(headless=False)
        context = await browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        )
        page = await context.new_page()

        print(f"[INFO] 正在打开: {url}")
        try:
            await page.goto(url, wait_until="networkidle", timeout=30000)
        except Exception as e:
            print(f"[ERROR] 页面加载失败: {e}")
            await browser.close()
            return

        current_url = page.url
        page_num = 1

        while page_num <= max_pages:
            print(f"\n[INFO] 正在处理第 {page_num} 页: {current_url}")

            # 等待页面稳定
            await asyncio.sleep(2)

            # 提取当前页面的文本内容
            page_text = await page.inner_text("body")
            # 提取所有链接
            links = await page.eval_on_selector_all(
                "a",
                "elements => elements.map(e => ({text: e.innerText.trim(), href: e.href}))"
            )
            # 过滤掉空链接和非内容链接
            content_links = [l for l in links if l["text"] and len(l["text"]) > 4 and "javascript:" not in l["href"]]

            page_data = {
                "page": page_num,
                "url": current_url,
                "page_text": page_text[:5000],  # 截断防止太长
                "links": content_links[:50]  # 最多取50条链接
            }
            results.append(page_data)
            print(f"[INFO] 第 {page_num} 页提取完成，找到 {len(content_links)} 个链接")

            # 检查是否有验证码
            page_text_lower = page_text.lower()
            if any(kw in page_text_lower for kw in ["验证码", "滑块", "人机验证", "captcha", "verify"]):
                print("\n[WARN] 检测到可能的人机验证，请手动完成验证后按回车继续...")
                input()

            # 翻页
            if page_num < max_pages:
                print(f"[INFO] 等待 {interval} 秒后翻页...")
                await asyncio.sleep(interval)

                # 尝试找下一页按钮
                next_selectors = [
                    "text=下一页",
                    "text=>",
                    ".next",
                    "#next",
                    "a:has-text('下一页')",
                    "li.next a"
                ]
                clicked = False
                for selector in next_selectors:
                    try:
                        next_btn = await page.query_selector(selector)
                        if next_btn and await next_btn.is_visible():
                            await next_btn.click()
                            await page.wait_for_load_state("networkidle", timeout=15000)
                            current_url = page.url
                            clicked = True
                            print(f"[INFO] 翻页成功，跳转到: {current_url}")
                            break
                    except:
                        continue

                if not clicked:
                    print("[WARN] 未找到下一页按钮，停止翻页")
                    break

            page_num += 1

        # 保存结果为JSON
        output_path = Path(output)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(results, f, ensure_ascii=False, indent=2)

        print(f"\n[INFO] 采集完成，结果已保存到: {output_path.resolve()}")
        print(f"[INFO] 共采集 {len(results)} 页数据")

        # 不自动关闭浏览器，让用户可以继续查看
        print("\n[INFO] 浏览器保持打开，你可以手动检查页面。按回车关闭浏览器...")
        input()
        await browser.close()


async def open_detail_page(url: str, output: str = "detail.txt"):
    """
    打开单个公告详情页，提取全文
    :param url: 公告详情页URL
    :param output: 输出文件路径
    """
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False)
        page = await browser.new_page()

        print(f"[INFO] 正在打开详情页: {url}")
        try:
            await page.goto(url, wait_until="networkidle", timeout=30000)
            await asyncio.sleep(2)

            # 提取正文
            body_text = await page.inner_text("body")

            output_path = Path(output)
            output_path.parent.mkdir(parents=True, exist_ok=True)
            with open(output_path, "w", encoding="utf-8") as f:
                f.write(f"URL: {url}\n")
                f.write(f"标题: {await page.title()}\n")
                f.write("=" * 60 + "\n")
                f.write(body_text)

            print(f"[INFO] 详情页内容已保存到: {output_path.resolve()}")

        except Exception as e:
            print(f"[ERROR] 打开详情页失败: {e}")

        print("\n[INFO] 按回车关闭浏览器...")
        input()
        await browser.close()


def export_to_csv(json_file: str, csv_file: str):
    """
    把JSON结果导出为CSV
    :param json_file: 输入JSON文件
    :param csv_file: 输出CSV文件
    """
    with open(json_file, "r", encoding="utf-8") as f:
        data = json.load(f)

    # 提取所有链接
    all_items = []
    for page in data:
        for link in page["links"]:
            all_items.append({
                "来源页": page["url"],
                "标题": link["text"],
                "链接": link["href"]
            })

    with open(csv_file, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["来源页", "标题", "链接"])
        writer.writeheader()
        writer.writerows(all_items)

    print(f"[INFO] CSV已导出: {csv_file}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="工程线索采集浏览器辅助工具")
    subparsers = parser.add_subparsers(dest="command")

    # 列表页采集
    browse_parser = subparsers.add_parser("browse", help="采集列表页")
    browse_parser.add_argument("--url", required=True, help="目标列表页URL")
    browse_parser.add_argument("--max-pages", type=int, default=3, help="最大翻页数")
    browse_parser.add_argument("--interval", type=int, default=4, help="翻页间隔秒数")
    browse_parser.add_argument("--output", default="output.json", help="输出JSON文件路径")

    # 详情页采集
    detail_parser = subparsers.add_parser("detail", help="采集单个详情页")
    detail_parser.add_argument("--url", required=True, help="详情页URL")
    detail_parser.add_argument("--output", default="detail.txt", help="输出文件路径")

    # 导出CSV
    export_parser = subparsers.add_parser("export", help="导出CSV")
    export_parser.add_argument("--input", required=True, help="输入JSON文件")
    export_parser.add_argument("--output", required=True, help="输出CSV文件")

    args = parser.parse_args()

    if args.command == "browse":
        asyncio.run(browse_page(args.url, args.max_pages, args.interval, args.output))
    elif args.command == "detail":
        asyncio.run(open_detail_page(args.url, args.output))
    elif args.command == "export":
        export_to_csv(args.input, args.output)
    else:
        parser.print_help()
