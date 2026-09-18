"""Offline DOM acceptance smoke using authored-synthetic API doubles.

Requires optional developer Playwright + Chromium, not a runtime dependency.
No navigation, Telegram, model providers or real archive requests are made.
This tests UI behavior only; HTTP authorization/service contracts are covered
separately in tests/unit/test_workspace_api.py and database behavior in CI.
"""

from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BOOTSTRAP = r"""<script>
window.Telegram={WebApp:{initData:"synthetic",ready(){},expand(){},BackButton:{show(){},hide(){},onClick(){}}}};
window.fixture={a:"00000000-0000-0000-0000-000000001001",b:"00000000-0000-0000-0000-000000001002",notes:[],writes:[],failOnce:true,calls:[],resolveOld:null};
window.fetch=async(url,options={})=>{
 const f=window.fixture,u=new URL(url,"https://fixture.invalid");let data={},status=200;
 f.calls.push({path:u.pathname,method:options.method||"GET"});
 const a={id:f.a,date:"2026-01-01",title:"Мост у дома",preview:"Я стою у деревянного моста."};
 const b={id:f.b,date:"2026-01-02",title:"Пустой сад",preview:"Я возвращаюсь в сад."};
 if(u.pathname==="/workspace/archive") data={items:[a,b],total:2,page:1,next_page:null};
 else if(u.pathname==="/workspace/search") {
   const q=JSON.parse(options.body).query;
   if(q==="старый запрос") return new Promise(resolve=>{f.resolveOld=()=>resolve(new Response(JSON.stringify({items:[{...a,title:"Устаревшая выдача"}],message:"old"}),{status:200}));});
   data={items:[a],message:"Найдена подборка, не весь архив."};
 }
 else if(u.pathname==="/workspace/research") {
   const ids=JSON.parse(options.body).dream_ids; f.researchIds=ids;
   data={state:"partial",requested_count:ids.length,read_count:1,source_ids:[f.a],answer:"Наблюдение: возвращение.\n01.01.26 Мост у дома: «Я стою у деревянного моста.»\nПрочитаны полностью: 1 из "+ids.length+" выбранных снов.\nЭто предложения для проверки."};
 }
 else if(u.pathname===`/workspace/dreams/${f.a}`||u.pathname===`/workspace/dreams/${f.b}`) data={...(u.pathname.endsWith(f.a)?a:b),raw_text:'Я стою у деревянного моста.\n<img src=x onerror=alert(1)> — синтетическая строка.',notes:[...f.notes]};
 else if(u.pathname.endsWith("/notes")){
   const v=JSON.parse(options.body);f.writes.push(v);
   const text=v.kind==="code"?"#"+v.text.replace(/^#+/,"").trim():v.text;
   if(!f.notes.includes(text))f.notes.push(text);
   if(f.failOnce){f.failOnce=false;status=503;data={detail:"Could not confirm note save"};}
   else data={saved:true,text,message:"Сохранено в заметках. Копия обновляется отдельно."};
 }
 else if(u.pathname==="/motifs/review") {
   const offset=Number(u.searchParams.get("offset")||0),confirmed=u.searchParams.get("status")==="confirmed";
   const count=confirmed?0:123; const items=[];
   for(let i=offset;i<Math.min(offset+20,count);i++)items.push({id:"00000000-0000-0000-0000-"+String(2000+i).padStart(12,"0"),dream_id:f.a,dream_title:"Мост у дома",dream_date:"2026-01-01",label:"Возвращение "+i,rationale:"Синтетический пример.",status:"draft",fragments:[{text:"Я стою у деревянного моста."}]});
   data={items,draft_count:123,confirmed_count:0,rejected_count:0,total_count:count,next_offset:offset+items.length<count?offset+items.length:null};
 } else throw new Error("Unmocked request");
 return new Response(JSON.stringify(data),{status,headers:{"Content-Type":"application/json"}});
};</script>"""


async def run(browser_path: str | None, output: Path) -> None:
    from playwright.async_api import async_playwright

    html = (ROOT / "app/static/dream_memory_map.html").read_text()
    shell = html.replace(
        '<script src="https://telegram.org/js/telegram-web-app.js"></script>', BOOTSTRAP
    )
    assert shell != html, "Telegram bootstrap was not replaced; refuse network execution"
    output.mkdir(parents=True, exist_ok=True)
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(executable_path=browser_path, headless=True)
        page = await browser.new_page(viewport={"width": 390, "height": 844}, device_scale_factor=1)
        page.set_default_timeout(6000)
        errors = []
        page.on("pageerror", lambda error: errors.append(str(error)))
        await page.route("**/*", lambda route: route.abort())
        await page.set_content(shell)
        await page.locator(".archive-card").first.wait_for()
        assert not await page.locator("#research-controls").get_attribute("open")
        await page.screenshot(path=str(output / "archive-mobile.png"), full_page=True)
        await page.locator(".archive-card").first.click()
        await page.locator("#reader-note-form").wait_for(state="visible")
        assert await page.locator("#reader-content img").count() == 0
        await page.locator("#note-kind").select_option("code")
        await page.locator("#note-text").fill("возвращение домой")
        await page.locator("#note-save").click()
        await page.wait_for_function(
            "document.getElementById('note-status').textContent.includes('Не удалось подтвердить')"
        )
        assert await page.locator("#note-text").input_value() == "возвращение домой"
        await page.locator("#note-save").click()
        await page.get_by_text("#возвращение домой", exact=True).wait_for()
        assert await page.evaluate("fixture.notes.length") == 1
        await page.screenshot(path=str(output / "reader-mobile.png"), full_page=True)
        await page.keyboard.press("Escape")
        assert not await page.locator("#dream-reader").is_visible()
        # Only an explicit selection action starts read-only synthesis.
        await page.locator("#research-controls summary").click()
        await page.locator("#select-visible").click()
        await page.locator("#research-run").click()
        await page.wait_for_function(
            "document.getElementById('research-answer').textContent.includes('1 из 2')"
        )
        assert await page.evaluate("fixture.researchIds.length") == 2
        assert "частичный" in await page.locator("#research-status").inner_text()
        assert await page.evaluate("fixture.writes.length") == 2
        # A late search cannot replace a newer result set.
        await page.locator("#archive-query").fill("старый запрос")
        await page.locator("#archive-search button").click()
        await page.wait_for_function("fixture.resolveOld !== null")
        await page.locator("#archive-recent").click()
        await page.wait_for_function("document.querySelectorAll('.archive-card').length === 2")
        await page.evaluate("fixture.resolveOld()")
        await page.wait_for_timeout(50)
        assert "Устаревшая выдача" not in await page.locator("#archive-list").inner_text()
        # Review pagination reaches proposals beyond the former first-100 limit.
        await page.locator("#review-tab").click()
        for expected in (40, 60, 80, 100, 120, 123):
            await page.locator("#review-more").click()
            await page.wait_for_function(
                "n => document.querySelectorAll('#review-list > article').length === n",
                arg=expected,
            )
        assert "123 из 123" in await page.locator("#review-total").inner_text()
        assert not await page.locator("#review-more").is_visible()
        await page.get_by_role("button", name="Добавить #код в заметки").first.click()
        await page.locator("#note-text").wait_for(state="visible")
        assert await page.locator("#note-text").input_value() == "Возвращение 0"
        assert await page.evaluate("fixture.writes.length") == 2
        await page.locator("#note-text").fill("")
        await page.keyboard.press("Escape")
        await page.locator('#review-view [data-filter="confirmed"]').click()
        await page.wait_for_function(
            "document.getElementById('review-total').textContent.includes('0 из 0')"
        )
        assert await page.locator("#draft-count").inner_text() == "123"
        await page.locator("#archive-tab").click()
        assert await page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
        await page.set_viewport_size({"width": 1280, "height": 900})
        await page.screenshot(path=str(output / "archive-desktop.png"), full_page=True)
        assert not errors, errors
        await browser.close()
    result = {
        "status": "pass",
        "mode": "offline DOM, synthetic API doubles; not live integration",
        "checks": [
            "mobile/desktop",
            "verbatim text/XSS",
            "unknown note save retains draft",
            "explicit code only",
            "partial research coverage",
            "late search ignored",
            "123-item review pagination",
            "global counts",
            "keyboard dialog",
            "no horizontal overflow",
        ],
    }
    (output / "smoke.json").write_text(json.dumps(result, ensure_ascii=False, indent=2))
    print(json.dumps(result, ensure_ascii=False))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--browser", help="Installed Chromium executable, or use Playwright default"
    )
    parser.add_argument("--output", type=Path, default=Path("/tmp/kolia-workspace-smoke"))
    args = parser.parse_args()
    asyncio.run(run(args.browser, args.output))


if __name__ == "__main__":
    main()
