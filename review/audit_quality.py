# -*- coding: utf-8 -*-
"""审计第三轮：近似重复、整条超长引用、前款指代完整性、标题截断清单、INS-0381详情"""
import openpyxl, re, collections

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

print('===== 1. 保险办法 第四十九条 完整条文与页码 =====')
a = arts[('保险销售行为管理办法', '第四十九条')]
print('page =', a['page'], '| text =', repr(a['text']))

print()
print('===== 2. quote 覆盖整条且原文很长（>250字，需评估拆分/过长） =====')
for r in rows:
    a = arts.get((r[I['doc_title']], r[I['article_no']]))
    if not a:
        continue
    qn, an = norm(r[I['quote_text']]), norm(a['text'])
    if len(an) > 250 and qn == an:
        print(f"{r[I['code']]} {r[I['article_no']]} 原文长={len(an)} title={r[I['title']]}")

print()
print('===== 3. 同文档近似重复 quote（公共前缀>30字 或 一方包含另一方） =====')
seen = []
for i, r in enumerate(rows):
    qn = norm(r[I['quote_text']])
    for r2 in rows[i+1:]:
        if r2[I['doc_title']] != r[I['doc_title']]:
            continue
        qn2 = norm(r2[I['quote_text']])
        if not qn or not qn2:
            continue
        if qn == qn2 or (len(qn) > 25 and qn in qn2) or (len(qn2) > 25 and qn2 in qn):
            print(f"{r[I['code']]} <-> {r2[I['code']]} | {r[I['article_no']]}/{r2[I['article_no']]} | 包含关系")
        else:
            # 公共前缀
            p = 0
            for ca, cb in zip(qn, qn2):
                if ca != cb:
                    break
                p += 1
            if p > 40:
                print(f"{r[I['code']]} <-> {r2[I['code']]} | {r[I['article_no']]}/{r2[I['article_no']]} | 公共前缀{p}字")

print()
print('===== 4. quote 含“前款/第一款/本条”指代，content 是否含上下文 =====')
for r in rows:
    q = str(r[I['quote_text']] or '')
    if re.search(r'前款|第一款|第（?[一二三]）?项所述|本条第', q):
        c = str(r[I['content']] or '')
        has_ctx = '适用条件与同条上下文' in c
        print(f"{r[I['code']]} {r[I['article_no']]} content含上下文={has_ctx} | quote={q[:60]}")

print()
print('===== 5. 标题截断候选（以“如何/在什么条件下”开头成分但句子不完整）逐条列出 quote 供改写 =====')
sus = ['KP-SEC-0064','KP-SEC-0069','KP-SEC-0112','KP-SEC-0117','KP-SEC-0128','KP-SEC-0141',
       'KP-SEC-0204','KP-SEC-0219','KP-SEC-0221','KP-SEC-0269','KP-SEC-0313','KP-SEC-0154',
       'KP-SEC-0232','KP-SEC-0089','KP-SEC-0096','KP-SEC-0098','KP-SEC-0101']
for r in rows:
    if r[I['code']] in sus:
        print('###', r[I['code']], r[I['article_no']])
        print('  title  :', r[I['title']])
        print('  quote  :', str(r[I['quote_text']])[:180].replace('\n', ' ⏎ '))
        print('  content:', str(r[I['content']])[:220].replace('\n', ' / '))
