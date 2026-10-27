# -*- coding: utf-8 -*-
"""审计第二轮：页码差异的成因、标题质量、相关依据交叉引用核对"""
import openpyxl, re, json, collections

XLSX = r'成员1_知识点审核.xlsx'
wb = openpyxl.load_workbook(XLSX, read_only=True)
ws = wb['知识点候选']
hdr = [c.value for c in next(ws.iter_rows(min_row=1, max_row=1))]
I = {h: i for i, h in enumerate(hdr)}
rows = list(ws.iter_rows(min_row=2, values_only=True))
arts = {}
for r in wb['完整条文'].iter_rows(min_row=2, values_only=True):
    arts[(r[0], r[1])] = {'text': r[2] or '', 'page': r[4]}

def norm(s):
    return re.sub(r'[\s\u3000]', '', str(s or ''))

print('========== A. 页码不一致行：quote 在原文中的起始位置 ==========')
for r in rows:
    code = r[I['code']]; doc = r[I['doc_title']]; art = r[I['article_no']]
    a = arts.get((doc, art))
    if not a:
        continue
    page = r[I['page_no']]
    if page in (None, '') or str(page) == str(a['page']):
        continue
    qn = norm(r[I['quote_text']]); an = norm(a['text'])
    pos = an.find(qn)
    print(f"{code} 候选页={page} 条文页={a['page']} 条文长={len(an)} quote起始位置={pos} 占比={pos/max(len(an),1):.0%}")
    print('   quote头:', str(r[I['quote_text']])[:40])
    print('   原文头:', a['text'][:40])

print()
print('========== B. 标题疑似截断或病句（>40字或结尾异常） ==========')
for r in rows:
    t = str(r[I['title']] or '')
    tn = norm(t)
    end_bad = re.search(r'(证|上|之|的|了|后|内|条|款|项)？$', t)
    if len(tn) > 42 or end_bad:
        print(f"{r[I['code']]} [{len(tn)}] {t}")

print()
print('========== C. content 中“相关依据”交叉引用核对 ==========')
for r in rows:
    c = str(r[I['content']] or '')
    for m in re.finditer(r'\n(第[一二三四五六七八九十百零]+条)相关依据：', c):
        cited = m.group(1)
        seg = c[m.end():]
        seg = seg.split('\n第')[0] if '\n第' in seg else seg
        a = arts.get((r[I['doc_title']], cited))
        ok = a and norm(seg[:60]) in norm(a['text'])
        print(f"{r[I['code']]} 本条={r[I['article_no']]} 引用={cited} 匹配={'OK' if ok else 'NO'} seg头={seg[:36]}")
    if re.search(r'相关依据', c) and not re.search(r'\n第[一二三四五六七八九十百零]+条相关依据：', c):
        print(f"{r[I['code']]} 相关依据格式异常:", c[c.find('相关依据')-20:c.find('相关依据')+40])

print()
print('========== D. 同条同 quote 近似重复（title 相同组详情） ==========')
for code in ['KP-SEC-0020', 'KP-SEC-0026', 'KP-SEC-0032']:
    for r in rows:
        if r[I['code']] == code:
            print(code, '| art=', r[I['article_no']], '| quote=', str(r[I['quote_text']])[:80])
            print('   content:', str(r[I['content']])[:150].replace('\n', ' / '))

print()
print('========== E. 每文档每条文的候选数（检查拆分是否合理） ==========')
cnt = collections.Counter((r[I['doc_title']], r[I['article_no']]) for r in rows)
big = [(k, v) for k, v in cnt.items() if v >= 4]
for k, v in sorted(big, key=lambda x: -x[1]):
    print(k, v)
