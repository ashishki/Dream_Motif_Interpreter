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
window.fixture={a:"00000000-0000-0000-0000-000000001001",b:"00000000-0000-0000-0000-000000001002",c:"00000000-0000-0000-0000-000000001003",motif:"00000000-0000-0000-0000-000000002000",node:"node-bridge",edge:"edge-return",notes:[],writes:[],calls:[],actions:[],downloads:[],confirms:0,failOnce:true,resolveOld:null,motifStatus:"draft",motifLabel:"Возвращение 0",hiddenNodes:[],hiddenEdges:[]};
window.confirm=()=>{window.fixture.confirms+=1;return true;};
HTMLAnchorElement.prototype.click=function(){if(this.download){window.fixture.downloads.push(this.download);}};
window.fetch=async(url,options={})=>{
 const f=window.fixture,u=new URL(url,"https://fixture.invalid");let data={},status=200;
 f.calls.push({path:u.pathname,method:options.method||"GET",url:u.href,body:options.body||null});
 const a={id:f.a,date:"2026-01-01",title:"Мост у дома",preview:"Я стою у деревянного моста."};
 const b={id:f.b,date:"2026-01-02",title:"Пустой сад",preview:"Я возвращаюсь в сад."};
 const c={id:f.c,date:"2026-01-03",title:"Тихая вода",preview:"Вода поднимается к порогу."};
 const motif=(index)=>({id:index===0?f.motif:"00000000-0000-0000-0000-"+String(2000+index).padStart(12,"0"),dream_id:f.a,dream_title:"Мост у дома",dream_date:"2026-01-01",label:index===0?f.motifLabel:"Возвращение "+index,rationale:"Синтетический пример.",status:index===0?f.motifStatus:"draft",fragments:[{text:"Я стою у деревянного моста."}]});
 const motifs=(filter)=>Array.from({length:123},(_,index)=>motif(index)).filter(item=>filter==="all"||item.status===filter);
 if(u.pathname==="/workspace/archive") {
   const page=Number(u.searchParams.get("page")||1); data=page===1?{items:[a,b],total:3,page:1,next_page:2}:{items:[c],total:3,page:2,next_page:null};
 } else if(u.pathname==="/workspace/search") {
   const q=JSON.parse(options.body).query;
   if(q==="старый запрос") return new Promise(resolve=>{f.resolveOld=()=>resolve(new Response(JSON.stringify({items:[{...a,title:"Устаревшая выдача"}],message:"old"}),{status:200}));});
   data={items:[a],message:"Найдена подборка, не весь архив."};
 } else if(u.pathname==="/workspace/research") {
   const ids=JSON.parse(options.body).dream_ids; f.researchIds=ids;
   data={state:"partial",requested_count:ids.length,read_count:1,source_ids:[f.a],answer:"Наблюдение: возвращение.\n01.01.26 Мост у дома: «Я стою у деревянного моста.»\nПрочитаны полностью: 1 из "+ids.length+" выбранных снов.\nЭто предложения для проверки."};
 } else if([f.a,f.b,f.c].some(id=>u.pathname===`/workspace/dreams/${id}`)) {
   const item=u.pathname.endsWith(f.a)?a:u.pathname.endsWith(f.b)?b:c;
   data={...item,raw_text:'Я стою у деревянного моста.\n<img src=x onerror=alert(1)> — синтетическая строка.',notes:[...f.notes]};
 } else if(u.pathname.endsWith("/notes")) {
   const value=JSON.parse(options.body);f.writes.push(value);
   const text=value.kind==="code"?"#"+value.text.replace(/^#+/,"").trim():value.text;
   if(!f.notes.includes(text))f.notes.push(text);
   if(f.failOnce){f.failOnce=false;status=503;data={detail:"Could not confirm note save"};}
   else data={saved:true,text,message:"Сохранено в заметках. Копия обновляется отдельно."};
 } else if(u.pathname==="/motifs/review") {
   const filter=u.searchParams.get("status")||"draft",offset=Number(u.searchParams.get("offset")||0),all=motifs(filter),items=all.slice(offset,offset+20);
   data={items,draft_count:motifs("draft").length,confirmed_count:motifs("confirmed").length,rejected_count:motifs("rejected").length,total_count:all.length,next_offset:offset+items.length<all.length?offset+items.length:null};
 } else if(u.pathname.startsWith(`/dreams/${f.a}/motifs/`)&&options.method==="PATCH") {
   const patch=JSON.parse(options.body);f.motifStatus=patch.status||f.motifStatus;f.motifLabel=patch.label||f.motifLabel;data={status:f.motifStatus,label:f.motifLabel};
 } else if(u.pathname===`/motifs/${f.motif}/research`) {
   data={parallels:[{label:"Переход через воду",relevance_note:"Проверяемая тематическая параллель",overlap_degree:"partial",source_url:"https://example.com/source"}]};
 } else if(u.pathname==="/dream-memory/state") {
   data={graph:{nodes:[{id:f.node,type:"Dream",label:"Мост у дома",confirmation_status:"confirmed"},{id:"motif-return",type:"Motif",label:"Возвращение",confirmation_status:"confirmed"}],edges:[{id:f.edge,type:"appears_in",source_node_id:f.node,target_node_id:"motif-return",confirmation_status:"confirmed",suggestion:{source_fragments:["Я стою у деревянного моста."]}}]},privacy_controls:{hidden_node_ids:[...f.hiddenNodes],hidden_edge_ids:[...f.hiddenEdges]}};
 } else if(u.pathname.startsWith("/dream-memory/privacy/")&&options.method==="POST") {
   const action=u.pathname.split("/").pop(),body=JSON.parse(options.body),list=body.subject_type==="graph_node"?f.hiddenNodes:f.hiddenEdges;
   if(action==="hide"&&!list.includes(body.subject_id))list.push(body.subject_id);
   if(action==="restore"){const index=list.indexOf(body.subject_id);if(index>=0)list.splice(index,1);}
   f.actions.push(action);data={saved:true};
 } else throw new Error("Unmocked request: "+u.pathname);
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
        # Archive controls: refresh, period and paginated list all use the same safe reader.
        await page.locator("#refresh").click()
        await page.locator("#period-controls summary").click()
        await page.locator("#archive-since").fill("2026-01-01")
        await page.locator("#archive-until").fill("2026-01-31")
        await page.locator("#archive-period").click()
        await page.wait_for_function(
            "fixture.calls.some(call => call.url.includes('since=2026-01-01') && call.url.includes('until=2026-01-31'))"
        )
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
        await page.locator("#reader-close").click()
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
        await page.locator("#research-download").click()
        await page.wait_for_function("fixture.downloads.includes('dream-archive-review.txt')")
        await page.locator("#clear-selected").click()
        assert "Выбрано: 0" == await page.locator("#selection-count").inner_text()
        await page.locator("#archive-more").click()
        await page.wait_for_function("document.querySelectorAll('.archive-card').length === 3")
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
        await page.locator("#review-list > article").first.wait_for()
        await page.screenshot(path=str(output / "review-mobile.png"), full_page=True)
        await page.locator("#refresh").click()
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
        await page.locator("#reader-close").click()
        await page.locator(".motif-label").first.fill("Возвращение домой")
        await page.get_by_role("button", name="Сохранить название").first.click()
        await page.wait_for_function("fixture.motifLabel === 'Возвращение домой'")
        await page.get_by_role("button", name="Открыть сон").first.click()
        await page.locator("#reader-note-form").wait_for(state="visible")
        await page.locator("#reader-close").click()
        await page.get_by_role("button", name="Подтвердить").first.click()
        await page.wait_for_function("fixture.motifStatus === 'confirmed'")
        await page.locator('#review-view [data-filter="confirmed"]').click()
        await page.wait_for_function(
            "document.getElementById('review-total').textContent.includes('1 из 1')"
        )
        await page.get_by_role("button", name="Найти параллели").click()
        await page.get_by_text("Внешние предположения — не выводы о сне:").wait_for()
        await page.get_by_role("button", name="Исключить из карты").click()
        await page.wait_for_function("fixture.motifStatus === 'rejected'")
        await page.locator('#review-view [data-filter="rejected"]').click()
        await page.get_by_role("button", name="Вернуть на проверку").click()
        await page.wait_for_function("fixture.motifStatus === 'draft'")
        await page.locator('#review-view [data-filter="all"]').click()
        await page.wait_for_function(
            "document.getElementById('review-total').textContent.includes('20 из 123')"
        )
        assert await page.locator("#draft-count").inner_text() == "123"
        # Map controls are visible only after selecting a graph item; exercise every stateful action.
        await page.locator("#map-tab").click()
        await page.locator(".node").first.wait_for()
        await page.screenshot(path=str(output / "map-mobile.png"), full_page=True)
        await page.locator(".node").first.click()
        assert not await page.locator("#exclude-map").is_disabled()
        await page.locator("#exclude-map").click()
        await page.wait_for_function("fixture.actions.includes('hide')")
        await page.locator("#scope").select_option("all_with_controls")
        await page.locator(".node").first.wait_for()
        await page.locator(".node").first.click()
        assert not await page.locator("#restore-map").is_disabled()
        await page.locator("#restore-map").click()
        await page.wait_for_function("fixture.actions.includes('restore')")
        await page.locator("#side-close").click()
        edge_box = await page.locator(".edge-hit").first.bounding_box()
        assert edge_box is not None
        await page.mouse.click(
            edge_box["x"] + edge_box["width"] / 2,
            edge_box["y"] + edge_box["height"] / 2,
        )
        await page.wait_for_function("!document.getElementById('reject-link').disabled")
        await page.locator("#reject-link").click()
        await page.wait_for_function("fixture.actions.includes('reject')")
        await page.locator("#side-close").click()
        assert "open" not in (await page.locator("#detail-sheet").get_attribute("class") or "")
        await page.locator("#scope").select_option("confirmed_only")
        await page.locator(".node").first.wait_for()
        await page.locator("#refresh").click()
        await page.set_viewport_size({"width": 1280, "height": 900})
        await page.screenshot(path=str(output / "map-desktop.png"), full_page=True)
        await page.locator("#archive-tab").click()
        assert await page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
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
            "period, refresh and archive pagination",
            "research text export confirmation",
            "late search ignored",
            "123-item review pagination",
            "review rename, decision, code, reader and parallel actions",
            "map scope, hide, restore and reject controls",
            "global counts",
            "reader dialog close",
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
