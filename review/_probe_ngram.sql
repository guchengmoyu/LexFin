-- ngram 全文检索误召回诊断（联调期临时脚本）
SELECT 'A_ngram命中样本' AS tag,
       code,
       ROUND(MATCH(title,content,keywords) AGAINST('偿付能力' IN NATURAL LANGUAGE MODE),3) AS score,
       LEFT(title,38) AS t
FROM knowledge_point
WHERE MATCH(title,content,keywords) AGAINST('偿付能力' IN NATURAL LANGUAGE MODE) > 0
ORDER BY score DESC LIMIT 6;

SELECT 'B_真实含偿付能力字样' AS tag,
       COUNT(*) AS real_hits
FROM knowledge_point
WHERE title LIKE '%偿付能力%' OR content LIKE '%偿付能力%' OR keywords LIKE '%偿付能力%';

SELECT 'C_单字能力命中' AS tag,
       COUNT(*) AS hits
FROM knowledge_point
WHERE MATCH(title,content,keywords) AGAINST('能力' IN NATURAL LANGUAGE MODE);

SELECT 'D_布尔短语精确匹配' AS tag,
       COUNT(*) AS bool_phrase_hits
FROM knowledge_point
WHERE MATCH(title,content,keywords) AGAINST('"偿付能力"' IN BOOLEAN MODE);

SELECT 'E_布尔AND_两词都需命中' AS tag,
       COUNT(*) AS bool_and_hits
FROM knowledge_point
WHERE MATCH(title,content,keywords) AGAINST('+偿付 +能力' IN BOOLEAN MODE);
