# -*- coding: utf-8 -*-
"""把 run_pipeline 里的单展项生成抽成 generate_exhibit()，run 支持 exhibit_id。

不改整批路径的行为：整批仍然先清空 exhibits 再逐个生成。
单展项路径只替换那一个，其余原样保留，版本仍 +0.1、自测照跑、审核失效。
"""
from pathlib import Path

p = Path(__file__).resolve().parent / "studio_server.py"
text = p.read_text(encoding="utf-8")

old_loop = '''            research_mode = not (project.get("materials") or [])
            drafts = []
            for index, unit in enumerate(units):
                exhibit = dict(unit)
                event(project_id, "step", {"step": "cards", "state": "running", "label": "知识卡",
                                           "detail": "正在处理 %s %s" % (exhibit["id"], exhibit.get("title", ""))})
                own = None if research_mode else (
                    project["sources"][index] if index < len(project["sources"]) else None)
                pool = [own] if own else all_sources(project)
                context = ""
                for source in pool:
                    for para in source["paragraphs"]:
                        context += "[%s] %s\\n" % (para["id"], para["text"])
                context = context[:12000]
                exhibit["source_refs"] = [source["id"] for source in pool]
                hint = ("资料段落（只能引用这里的 [编号]）：" if own else
                        "来源段落（员工资料 SRC-… 与联网摘录 WEB-… 混排，只能引用这里的 [编号]）：")
                messages = [
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content":
                        "展项编号：%s\\n展项名称：%s\\n观众：%s\\n\\n%s\\n%s\\n\\n请为这个展项输出 JSON。"
                        % (exhibit["id"], exhibit.get("title", ""), project.get("audience", "亲子观众"),
                           hint, context)},
                ]
                try:
                    data = model_json(messages, project_id, max_tokens=4000)
                except ModelError as error:
                    event(project_id, "error", {"message": "模型调用失败：" + str(error)})
                    project["status"] = "failed"
                    project["error"] = str(error)
                    save(project)
                    return
                item = dict(exhibit)
                item.update({
                    "title": str(data.get("title") or exhibit["title"])[:60],
                    "facts": data.get("facts") or [],
                    "main": data.get("main") or {"text": ""},
                    "simplified": data.get("simplified") or {"text": ""},
                    "followups": data.get("followups") or [],
                    "fallback": data.get("fallback") or [],
                })
                if not item["main"].get("text"):
                    item["issues"] = [{"id": "IS-EMPTY-" + exhibit["id"], "exhibit_id": exhibit["id"],
                                       "title": "没有生成主讲解", "detail": "模型返回的主讲解为空，需要重新生成。",
                                       "actions": ["重新生成", "补充资料"]}]
                    item["verified"] = False
                else:
                    item = verify(project, item)
                drafts.append(item)
                project["exhibits"] = drafts
                project["issues"] = [issue for draft in drafts for issue in draft.get("issues", [])]
                save(project)
                event(project_id, "step", {"step": "cards", "state": "done", "label": "知识卡",
                                           "detail": "%s：%d 条事实，%d 处待核验" % (
                                               item["id"], len(item["facts"]), len(item.get("issues", [])))})
'''

new_loop = '''            research_mode = not (project.get("materials") or [])
            drafts = []
            for index, unit in enumerate(units):
                item = generate_exhibit(project, unit, index, research_mode)
                if item is None:
                    return
                drafts.append(item)
                project["exhibits"] = drafts
                project["issues"] = [issue for draft in drafts for issue in draft.get("issues", [])]
                save(project)
'''

helper = '''def generate_exhibit(project, unit, index, research_mode):
    """生成一个展项。整批与单个共用这一条路径，保证行为一致。

    返回生成并校验后的展项；模型失败时把项目置 failed 并返回 None。
    """
    project_id = project["id"]
    exhibit = dict(unit)
    event(project_id, "step", {"step": "cards", "state": "running", "label": "知识卡",
                               "detail": "正在处理 %s %s" % (exhibit["id"], exhibit.get("title", ""))})
    own = None if research_mode else (
        project["sources"][index] if index < len(project.get("sources", [])) else None)
    pool = [own] if own else all_sources(project)
    context = ""
    for source in pool:
        for para in source["paragraphs"]:
            context += "[%s] %s\\n" % (para["id"], para["text"])
    context = context[:12000]
    exhibit["source_refs"] = [source["id"] for source in pool]
    hint = ("资料段落（只能引用这里的 [编号]）：" if own else
            "来源段落（员工资料 SRC-… 与联网摘录 WEB-… 混排，只能引用这里的 [编号]）：")
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content":
            "展项编号：%s\\n展项名称：%s\\n观众：%s\\n\\n%s\\n%s\\n\\n请为这个展项输出 JSON。"
            % (exhibit["id"], exhibit.get("title", ""), project.get("audience", "亲子观众"),
               hint, context)},
    ]
    try:
        data = model_json(messages, project_id, max_tokens=4000)
    except ModelError as error:
        event(project_id, "error", {"message": "模型调用失败：" + str(error)})
        project["status"] = "failed"
        project["error"] = str(error)
        save(project)
        return None
    item = dict(exhibit)
    item.update({
        "title": str(data.get("title") or exhibit["title"])[:60],
        "facts": data.get("facts") or [],
        "main": data.get("main") or {"text": ""},
        "simplified": data.get("simplified") or {"text": ""},
        "followups": data.get("followups") or [],
        "fallback": data.get("fallback") or [],
    })
    if not item["main"].get("text"):
        item["issues"] = [{"id": "IS-EMPTY-" + exhibit["id"], "exhibit_id": exhibit["id"],
                           "title": "没有生成主讲解", "detail": "模型返回的主讲解为空，需要重新生成。",
                           "actions": ["重新生成", "补充资料"]}]
        item["verified"] = False
    else:
        item = verify(project, item)
    event(project_id, "step", {"step": "cards", "state": "done", "label": "知识卡",
                               "detail": "%s：%d 条事实，%d 处待核验" % (
                                   item["id"], len(item["facts"]), len(item.get("issues", [])))})
    return item


def run_single_exhibit(project_id, exhibit_id):
    """只重新生成一个展项，其余展项原样保留。

    与整批一样：版本 +0.1、自测重跑、审核失效（内容变了旧签名就不能再用）。
    """
    def work():
        try:
            project = load(project_id)
            units = exhibit_units(project)
            target = None
            index = 0
            for i, unit in enumerate(units):
                if unit["id"] == exhibit_id:
                    target = unit
                    index = i
                    break
            if target is None:
                project["status"] = "failed"
                project["error"] = "展项不在本轮清单里：" + exhibit_id
                save(project)
                event(project_id, "error", {"message": project["error"]})
                return
            project["status"] = "running"
            project["run_version"] = project.get("run_version", 0) + 1
            project["version"] = round(project.get("version", 0) + 0.1, 1)
            project["review"] = None
            save(project)
            research_mode = not (project.get("materials") or [])
            item = generate_exhibit(project, target, index, research_mode)
            if item is None:
                return
            replaced = False
            for i, old in enumerate(project.get("exhibits", [])):
                if old["id"] == exhibit_id:
                    project["exhibits"][i] = item
                    replaced = True
                    break
            if not replaced:
                project.setdefault("exhibits", []).append(item)
            project["issues"] = [issue for draft in project["exhibits"] for issue in draft.get("issues", [])]
            project["tests"] = content_tests(project)
            failed = [row for row in project["tests"] if row.get("status") != "passed"]
            project["status"] = "awaiting_confirmation" if (project["issues"] or failed) else "tested"
            save(project)
            event(project_id, "run.finished", {
                "message": "%s 已重新生成；自测 %d/%d 通过" % (
                    exhibit_id, len(project["tests"]) - len(failed), len(project["tests"])),
                "exhibit_id": exhibit_id})
        except Exception as error:
            traceback.print_exc()
            try:
                project = load(project_id)
                project["status"] = "failed"
                project["error"] = "%s: %s" % (type(error).__name__, error)
                save(project)
            except Exception:
                pass
            event(project_id, "error", {"message": "单展项生成异常：" + str(error)})

    threading.Thread(target=work, daemon=True).start()


def run_pipeline(project_id):'''

if old_loop not in text:
    raise SystemExit("loop not found")
text = text.replace(old_loop, new_loop, 1)
text = text.replace("def run_pipeline(project_id):", helper, 1)

# run 支持 exhibit_id
old_run = '''            if action == "run":
                if project["status"] == "running":
                    return self.send_json(409, {"error": "正在执行，请等待本轮结束"})'''
new_run = '''            if action == "run":
                if project["status"] == "running":
                    return self.send_json(409, {"error": "正在执行，请等待本轮结束"})
                only = str(data.get("exhibit_id") or "").strip()[:16]
                if only:
                    if project.get("exhibits") and not any(
                            e["id"] == only for e in project["exhibits"]):
                        return self.send_json(404, {"error": "展项不存在：" + only})
                    run_single_exhibit(project_id, only)
                    return self.send_json(202, {"status": "running", "exhibit_id": only})'''
if old_run not in text:
    raise SystemExit("run route not found")
text = text.replace(old_run, new_run, 1)

p.write_text(text, encoding="utf-8", newline="\n")
print("single-exhibit generation added")
