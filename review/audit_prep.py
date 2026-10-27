# -*- coding: utf-8 -*-
"""改写前精确调取：待修复标题行的 title/quote 全文，重复疑点行，effective_date 取值"""
import openpyxl

wb = openpyxl.load_workbook(r'成员1_知识点审核.xlsx', read_only=True)
ws = wb['知识点候选']
hdr = [c.value for c in next(ws.iter_rows(min_row=1, max_row=1))]
I = {h: i for i, h in enumerate(hdr)}
rows = list(ws.iter_rows(min_row=2, values_only=True))
d = {r[I['code']]: r for r in rows}

fix = ['KP-SEC-0064','KP-SEC-0069','KP-SEC-0070','KP-SEC-0080','KP-SEC-0089','KP-SEC-0096',
       'KP-SEC-0098','KP-SEC-0101','KP-SEC-0112','KP-SEC-0117','KP-SEC-0128','KP-SEC-0141',
       'KP-SEC-0154','KP-SEC-0177','KP-SEC-0204','KP-SEC-0219','KP-SEC-0221','KP-SEC-0232',
       'KP-SEC-0266','KP-SEC-0269','KP-SEC-0276','KP-SEC-0296','KP-SEC-0313']
for c in fix:
    r = d[c]
    print('###', c, r[I['article_no']])
    print('  title :', r[I['title']])
    print('  quote :', str(r[I['quote_text']])[:300].replace('\n', ' ⏎ '))

print()
print('===== 重复疑点 KP-SEC-0025 / KP-SEC-0031 =====')
for c in ['KP-SEC-0025','KP-SEC-0031']:
    r = d[c]
    print('###', c, r[I['article_no']])
    print('  title :', r[I['title']])
    print('  quote :', str(r[I['quote_text']])[:200].replace('\n', ' ⏎ '))

print()
print('===== effective_date / timeliness / doc_no 按文档取值 =====')
import collections
print(collections.Counter((r[I['doc_title']], r[I['effective_date']], r[I['doc_no']]) for r in rows))
